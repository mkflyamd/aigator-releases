"""Graph-backed storage for shared skills: folders, small files and permissions.

Every method raises ShareError. Nothing here deletes anything.
"""

import json
from urllib.parse import quote, unquote

from .._files.errors import classify_graph_error, http_status
from .._m365 import file_transfer as ft
from .errors import ShareError

ROOT_FOLDER_NAME = "AI Gator Skills"
JSON_MAX_BYTES = 1024 * 1024

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

    def default_root(self, create: bool = True) -> dict | None:
        item = self._get_or_create_folder(
            f"/me/drive/root:/{_q(ROOT_FOLDER_NAME)}", "/me/drive/root/children", ROOT_FOLDER_NAME, create
        )
        return _ref(item) if item else None

    def child_folder(self, parent: dict, name: str, create: bool = True) -> dict | None:
        base = f"/drives/{_q(parent['drive_id'])}/items/{_q(parent['folder_id'])}"
        item = self._get_or_create_folder(f"{base}:/{_q(name)}", f"{base}/children", name, create)
        return _ref(item, parent["drive_id"]) if item else None

    def _get(self, path: str, **params) -> dict:
        try:
            out = self._gc.get(path, params=params) if params else self._gc.get(path)
        except Exception as e:
            raise _fail(e) from e
        return out if isinstance(out, dict) else {}

    def my_drive_id(self) -> str:
        return self._get("/me/drive", **{"$select": "id"}).get("id", "")

    def my_user_id(self) -> str:
        """The signed-in user's stable directory id, the identity a shared skill's ownership is checked against."""
        return self._get("/me", **{"$select": "id"}).get("id", "")

    def describe_folder(self, drive_id: str, folder_id: str) -> dict:
        """The folder as a location with a display path. Raises not_found, or invalid when it is not a folder."""
        item = self._get(
            f"/drives/{_q(drive_id)}/items/{_q(folder_id)}",
            **{"$select": "id,name,webUrl,folder,root,parentReference"},
        )
        if not item.get("id"):
            raise ShareError("not_found", _MESSAGES["not_found"])
        if "folder" not in item:
            raise ShareError("invalid", "That is a file, not a folder.")
        drive = self._get(f"/drives/{_q(drive_id)}", **{"$select": "name"})
        path = [drive.get("name") or "OneDrive"]
        if "root" not in item:
            parent = (item.get("parentReference") or {}).get("path", "")
            path += [unquote(seg) for seg in parent.partition("root:")[2].split("/") if seg]
            path.append(item.get("name", ""))
        return {
            "drive_id": drive_id,
            "folder_id": item["id"],
            "name": item.get("name", ""),
            "path": path,
            "web_url": item.get("webUrl", ""),
        }

    def audience(self, drive_id: str, folder_id: str, name: str) -> dict:
        """Who can already see inside this folder: private, library, anyone, org or folder."""
        drive = self._get(f"/drives/{_q(drive_id)}", **{"$select": "name,driveType"})
        if drive.get("driveType") == "documentLibrary":
            return {"kind": "library", "name": drive.get("name") or name, "approx_count": None}
        try:
            perms = self._gc.get(f"/drives/{_q(drive_id)}/items/{_q(folder_id)}/permissions")
        except Exception:
            return {"kind": "folder", "name": name, "approx_count": None}
        entries = perms.get("value", []) if isinstance(perms, dict) else []
        scopes = {(entry.get("link") or {}).get("scope") for entry in entries}
        if "anonymous" in scopes:
            return {"kind": "anyone", "name": "Anyone with the link", "approx_count": None}
        if "organization" in scopes:
            return {"kind": "org", "name": "Your organization", "approx_count": None}
        others = [e for e in entries if "owner" not in (e.get("roles") or [])]
        if others or drive_id != self.my_drive_id():
            return {"kind": "folder", "name": name, "approx_count": len(others) or None}
        return {"kind": "private", "name": "Only you", "approx_count": None}

    def read_file(self, folder: dict, name: str, max_bytes: int | None = None) -> tuple[bytes, str] | None:
        drive = _q(folder["drive_id"])
        try:
            item = self._gc.get(f"/drives/{drive}/items/{_q(folder['folder_id'])}:/{_q(name)}")
        except Exception as e:
            if http_status(e) == 404:
                return None
            raise _fail(e) from e
        if not isinstance(item, dict) or not item.get("id"):
            return None
        size = item.get("size")
        if max_bytes is not None and isinstance(size, int) and size > max_bytes:
            raise ShareError("too_large", f"{name} in the shared folder is too large to open.")
        try:
            data = self._gc.get_bytes(f"/drives/{drive}/items/{_q(item['id'])}/content")
        except Exception as e:
            raise _fail(e) from e
        return data, item.get("eTag", "")

    def read_json(self, folder: dict, name: str, max_bytes: int = JSON_MAX_BYTES) -> tuple[dict, str] | None:
        found = self.read_file(folder, name, max_bytes)
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

    def write_file_create(self, folder: dict, name: str, data: bytes) -> None:
        """Create the file; raises conflict when it already exists, so a published version is never overwritten."""
        self._check(
            ft.store_in_folder(
                self._gc, ft.bytes_source(name, data), folder["drive_id"], folder["folder_id"], on_conflict="fail"
            )
        )

    def write_json_create(self, folder: dict, name: str, doc: dict) -> None:
        source = ft.bytes_source(name, json.dumps(doc, indent=2, sort_keys=True).encode("utf-8"))
        self._check(ft.store_in_folder(self._gc, source, folder["drive_id"], folder["folder_id"], on_conflict="fail"))

    def write_json_replace(self, folder: dict, name: str, doc: dict, etag: str) -> None:
        if not etag:
            # replace_in_folder treats an empty If-Match as an unconditional replace.
            raise ShareError("conflict", _MESSAGES["conflict"])
        source = ft.bytes_source(name, json.dumps(doc, indent=2, sort_keys=True).encode("utf-8"))
        self._check(ft.replace_in_folder(self._gc, source, folder["drive_id"], folder["folder_id"], if_match=etag))

    def grant_read(self, folder: dict, emails: list[str]) -> list[str]:
        """Give each address read access. Returns the addresses Graph would not accept.

        One invite covers everyone. If Graph rejects it with a 400 (an address
        outside the tenant or one it cannot resolve), each address is invited
        on its own so one bad address does not block the rest. Any other
        failure still raises.
        """
        if not emails:
            return []
        path = f"/drives/{_q(folder['drive_id'])}/items/{_q(folder['folder_id'])}/invite"

        def invite(batch: list[str]) -> None:
            self._gc.post(
                path,
                {
                    "recipients": [{"email": e} for e in batch],
                    "roles": ["read"],
                    "requireSignIn": True,
                    "sendInvitation": False,
                },
            )

        try:
            invite(emails)
            return []
        except Exception as e:
            if http_status(e) != 400:
                raise _fail(e) from e
        ungranted = []
        for email in emails:
            try:
                invite([email])
            except Exception as e:
                if http_status(e) != 400:
                    raise _fail(e) from e
                ungranted.append(email)
        return ungranted
