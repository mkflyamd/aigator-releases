"""OneDrive/SharePoint provider for skills._files.transfer.

Wraps the existing OneDrive tool functions (passed in, so this module never imports the
skill) and the shared upload primitives; nothing is reimplemented. Every method returns a
result dict, never raises: failures carry ``error`` and an ``error_code``. Nothing here
deletes anything, locally or in OneDrive.
"""

import os
from pathlib import Path
from urllib.parse import quote

from .._files.errors import classify_graph_error, http_status
from . import file_transfer as ft


def _q(value: str) -> str:
    return quote(value or "", safe="")


def _failure(prefix: str, exc: Exception) -> dict:
    return {"error": f"{prefix}: {exc}", "error_code": classify_graph_error(exc)}


def _coded(out: dict) -> dict:
    """Make sure a tool's error result carries an error_code."""
    if isinstance(out, dict) and "error" in out and not out.get("error_code"):
        return {**out, "error_code": "unknown"}
    return out


class OneDriveProvider:
    def __init__(self, *, get_item, download, copy, move, client):
        self._get_item = get_item
        self._download = download
        self._copy = copy
        self._move = move
        self._client = client

    def stat(self, ref):
        try:
            return _coded(self._get_item(ref["drive_id"], ref["item_id"]))
        except Exception as e:
            return _failure("Could not get the file", e)

    def is_foreign_owner(self, ref):
        """True when the file sits in another person's OneDrive, or that cannot be checked."""
        try:
            gc = self._client()
            drive = gc.get(f"/drives/{_q(ref['drive_id'])}", params={"$select": "id,driveType"})
            mine = gc.get("/me/drive", params={"$select": "id"})
        except Exception:
            return True
        return drive.get("driveType") in ("business", "personal") and drive.get("id") != mine.get("id")

    def move(self, ref, dest_folder, new_name):
        try:
            return _coded(
                self._move(ref["drive_id"], ref["item_id"], dest_folder["drive_id"], dest_folder["folder_id"], new_name)
            )
        except Exception as e:
            return _failure("Move failed", e)

    def copy(self, ref, dest_folder, new_name):
        try:
            return _coded(
                self._copy(ref["drive_id"], ref["item_id"], dest_folder["drive_id"], dest_folder["folder_id"], new_name)
            )
        except Exception as e:
            out = _failure("Copy failed", e)
            if not http_status(e):
                out["ambiguous"] = True  # no HTTP answer: the copy may still have been started
            return out

    def find_in_folder(self, dest_folder, name, size):
        """The item called ``name`` in the folder, or None (also when it cannot be looked up)."""
        try:
            item = self._client().get(
                f"/drives/{_q(dest_folder['drive_id'])}/items/{_q(dest_folder['folder_id'])}:/{_q(name)}"
            )
        except Exception:
            return None
        if not isinstance(item, dict) or not item.get("id"):
            return None
        if size is not None and item.get("size") != size:
            return None
        pr = item.get("parentReference") or {}
        return {
            "item_id": item["id"],
            "drive_id": pr.get("driveId", dest_folder["drive_id"]),
            "name": item.get("name", name),
            "web_url": item.get("webUrl", ""),
        }

    def download(self, ref, local_path):
        """Save the file to ``local_path``, which must not exist yet: it is never overwritten.

        The path is claimed with an exclusive create before the tool writes into it.
        """
        dest = Path(local_path).expanduser()
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "xb"):
                pass
        except FileExistsError:
            return {"error": f"A local file already exists at {dest}; it was not overwritten.", "error_code": "conflict"}
        except Exception as e:
            return _failure("Could not create the local file", e)
        try:
            out = _coded(self._download(file_id=ref["item_id"], drive_id=ref["drive_id"], local_path=local_path))
        except Exception as e:
            out = _failure("Download failed", e)
        if "error" in out:
            out["error"] += f" (an empty placeholder file was left at {dest})"
        return out

    def upload(self, local_path, dest_folder, name=""):
        path = os.path.expanduser(local_path)
        try:
            source = ft.file_source(path, name)
            out = ft.store_in_folder(self._client(), source, dest_folder["drive_id"], dest_folder["folder_id"])
        except FileNotFoundError:
            return {"error": f"Local file not found: {local_path}", "error_code": "not_found"}
        except Exception as e:
            return _failure("Upload failed", e)
        if out.get("status") == "saved":
            return {
                "item_id": out["id"],
                "drive_id": out["drive_id"],
                "name": out["name"],
                "web_url": out["web_url"],
                "size": out["size"],
            }
        return {
            "error": out.get("detail") or out.get("hint") or out.get("error") or "Upload failed",
            "error_code": out.get("error_code") or "unknown",
        }
