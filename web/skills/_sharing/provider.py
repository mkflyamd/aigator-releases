"""Graph-backed storage for shared skills: folders, small files and permissions.

Every method raises ShareError. Nothing here deletes anything.
"""

import json
from urllib.parse import quote

from .._files.errors import classify_graph_error, http_status
from .._m365 import file_transfer as ft
from .errors import ShareError

ROOT_FOLDER_NAME = "AI Gator Skills"

_MESSAGES = {
    "forbidden": "You do not have permission to do that in this OneDrive folder.",
    "not_found": "That OneDrive folder or file could not be found.",
    "conflict": "The shared skill was changed by someone else. Reload it and try again.",
    "throttled": "OneDrive is busy. Try again in a minute.",
    "locked": "The file is locked in OneDrive. Try again later.",
}


def _q(value: str) -> str:
    return quote(value or "", safe="")


def _fail(exc: Exception) -> ShareError:
    code = classify_graph_error(exc)
    return ShareError(code, _MESSAGES.get(code) or f"OneDrive request failed: {str(exc)[:200]}")


def _ref(item: dict, drive_id: str = "") -> dict:
    drive_id = drive_id or (item.get("parentReference") or {}).get("driveId", "")
    if not drive_id or not item.get("id"):
        raise ShareError("unknown", "OneDrive returned a folder without an ID.")
    return {
        "drive_id": drive_id,
        "folder_id": item["id"],
        "web_url": item.get("webUrl", ""),
        "name": item.get("name", ""),
    }


class GraphSharingProvider:
    def __init__(self, gc):
        self._gc = gc

    def _get_or_create_folder(self, get_path: str, post_path: str, name: str, create: bool) -> dict | None:
        try:
            item = self._gc.get(get_path)
        except Exception as e:
            if http_status(e) != 404:
                raise _fail(e) from e
            if not create:
                return None
            body = {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}
            try:
                item = self._gc.post(post_path, body)
            except Exception as e2:
                if http_status(e2) != 409:
                    raise _fail(e2) from e2
                try:
                    item = self._gc.get(get_path)
                except Exception as e3:
                    raise _fail(e3) from e3
        if not isinstance(item, dict) or "folder" not in item:
            raise ShareError("conflict", f"'{name}' already exists in OneDrive and is not a folder.")
        return item

    def default_root(self) -> dict:
        item = self._get_or_create_folder(
            f"/me/drive/root:/{_q(ROOT_FOLDER_NAME)}", "/me/drive/root/children", ROOT_FOLDER_NAME, True
        )
        return _ref(item)

    def child_folder(self, parent: dict, name: str, create: bool = True) -> dict | None:
        base = f"/drives/{_q(parent['drive_id'])}/items/{_q(parent['folder_id'])}"
        item = self._get_or_create_folder(f"{base}:/{_q(name)}", f"{base}/children", name, create)
        return _ref(item, parent["drive_id"]) if item else None

    def read_file(self, folder: dict, name: str) -> tuple[bytes, str] | None:
        drive = _q(folder["drive_id"])
        try:
            item = self._gc.get(f"/drives/{drive}/items/{_q(folder['folder_id'])}:/{_q(name)}")
        except Exception as e:
            if http_status(e) == 404:
                return None
            raise _fail(e) from e
        if not isinstance(item, dict) or not item.get("id"):
            return None
        try:
            data = self._gc.get_bytes(f"/drives/{drive}/items/{_q(item['id'])}/content")
        except Exception as e:
            raise _fail(e) from e
        return data, item.get("eTag", "")

    def read_json(self, folder: dict, name: str) -> tuple[dict, str] | None:
        found = self.read_file(folder, name)
        if found is None:
            return None
        data, etag = found
        try:
            doc = json.loads(data.decode("utf-8"))
        except ValueError as e:
            raise ShareError("invalid", f"{name} in the shared folder is not valid.") from e
        if not isinstance(doc, dict):
            raise ShareError("invalid", f"{name} in the shared folder is not valid.")
        return doc, etag

    def _check(self, out: dict) -> None:
        if out.get("status") == "saved":
            return
        code = out.get("error_code") or "unknown"
        raise ShareError(
            code, _MESSAGES.get(code) or f"Upload to OneDrive failed: {out.get('detail') or out.get('error')}"
        )

    def write_file(self, folder: dict, name: str, data: bytes) -> None:
        self._check(ft.replace_in_folder(self._gc, ft.bytes_source(name, data), folder["drive_id"], folder["folder_id"]))

    def write_json_create(self, folder: dict, name: str, doc: dict) -> None:
        source = ft.bytes_source(name, json.dumps(doc, indent=2, sort_keys=True).encode("utf-8"))
        self._check(ft.store_in_folder(self._gc, source, folder["drive_id"], folder["folder_id"], on_conflict="fail"))

    def write_json_replace(self, folder: dict, name: str, doc: dict, etag: str) -> None:
        if not etag:
            # replace_in_folder treats an empty If-Match as an unconditional replace.
            raise ShareError("conflict", _MESSAGES["conflict"])
        source = ft.bytes_source(name, json.dumps(doc, indent=2, sort_keys=True).encode("utf-8"))
        self._check(ft.replace_in_folder(self._gc, source, folder["drive_id"], folder["folder_id"], if_match=etag))

    def grant_read(self, folder: dict, emails: list[str]) -> None:
        if not emails:
            return
        body = {
            "recipients": [{"email": e} for e in emails],
            "roles": ["read"],
            "requireSignIn": True,
            "sendInvitation": False,
        }
        try:
            self._gc.post(f"/drives/{_q(folder['drive_id'])}/items/{_q(folder['folder_id'])}/invite", body)
        except Exception as e:
            raise _fail(e) from e
