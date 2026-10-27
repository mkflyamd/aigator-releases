"""Store a byte source into OneDrive/SharePoint: copy only, never overwrite, never delete.

New transfer use cases plug in by building a `Source`; the upload, conflict and
verification rules live here once.
"""

import hashlib
import re
import urllib.parse
from dataclasses import dataclass
from typing import Callable, Iterator

SIMPLE_UPLOAD_MAX = 4 * 1024 * 1024
CHUNK = 320 * 1024 * 10

_BAD_CHARS = re.compile(r'["*:<>?/\\|#%]')


@dataclass
class Source:
    name: str
    size: int
    open: Callable[[], Iterator[bytes]]


def bytes_source(name: str, data: bytes) -> Source:
    return Source(name=name, size=len(data), open=lambda: iter([data]))


def safe_filename(name: str) -> str:
    cleaned = _BAD_CHARS.sub("_", name or "").strip().strip(".").strip()
    return cleaned or "file"


def _base(drive_id: str) -> str:
    return f"/drives/{drive_id}" if drive_id else "/me/drive"


def _status(e: Exception):
    return getattr(e, "status_code", None)


def _item_path(drive_id: str, folder_path: str, name: str = "") -> str:
    parts = [p for p in [folder_path.strip("/"), name] if p]
    return f"{_base(drive_id)}/root:/{'/'.join(parts)}" if parts else f"{_base(drive_id)}/root"


def ensure_folder(gc, drive_id: str, folder_path: str) -> list:
    """Create any missing folders; return [{"path", "web_url"}] for each segment."""
    done = ""
    chain = []
    for seg in [s for s in folder_path.strip("/").split("/") if s]:
        seg = safe_filename(seg)
        current = f"{done}/{seg}" if done else seg
        try:
            item = gc.get(_item_path(drive_id, current))
        except Exception as e:
            if _status(e) != 404:
                raise
            parent = (
                f"{_base(drive_id)}/root:/{done}:/children"
                if done
                else f"{_base(drive_id)}/root/children"
            )
            try:
                item = gc.post(
                    parent,
                    {
                        "name": seg,
                        "folder": {},
                        "@microsoft.graph.conflictBehavior": "fail",
                    },
                )
            except Exception as e2:
                if _status(e2) != 409:
                    raise
                item = gc.get(_item_path(drive_id, current))
        chain.append({"path": current, "web_url": (item or {}).get("webUrl", "")})
        done = current
    return chain


def _rechunk(pieces: Iterator[bytes], size: int) -> Iterator[bytes]:
    buf = bytearray()
    for piece in pieces:
        buf += piece
        while len(buf) >= size:
            yield bytes(buf[:size])
            del buf[:size]
    if buf:
        yield bytes(buf)


def _result(status: str, **kw) -> dict:
    return {"status": status, **kw}


def _existing(item: dict, drive_id: str) -> dict:
    return {
        "name": item.get("name", ""),
        "id": item.get("id", ""),
        "web_url": item.get("webUrl", ""),
        "size": item.get("size"),
        "drive_id": drive_id,
    }


def _existing_result(found: dict, source: Source, drive_id: str, folder_info: dict) -> dict:
    """The file is already there: report it as saved only when its size is the source's."""
    if found.get("size") != source.size:
        return _result(
            "error",
            error="existing_file_size_mismatch",
            expected_size=source.size,
            reported_size=found.get("size"),
            hint=(
                "A file with this name is already in the folder but its size differs from the source, "
                "so it may be a partial upload. It was not overwritten. Do not report it as saved; "
                "ask the user to delete or rename it, then save again."
            ),
            **_existing(found, drive_id),
        )
    return _result("exists", **_existing(found, drive_id), **folder_info)


def _upload_small(gc, source, drive_id, folder_path, name):
    data = b"".join(source.open())
    if len(data) != source.size:
        return None, "source_size_mismatch", hashlib.sha256(data).hexdigest()
    path = _item_path(drive_id, folder_path, name) + ":/content?@microsoft.graph.conflictBehavior=fail"
    item = gc.put_binary(path, data)
    return item, "", hashlib.sha256(data).hexdigest()


def _upload_large(gc, source, drive_id, folder_path, name):
    session = gc.post(
        _item_path(drive_id, folder_path, name) + ":/createUploadSession",
        {"item": {"@microsoft.graph.conflictBehavior": "fail", "name": name}},
    )
    url = session["uploadUrl"]
    digest = hashlib.sha256()
    sent = 0
    item = None
    try:
        for block in _rechunk(source.open(), CHUNK):
            if sent + len(block) > source.size:
                break
            end = sent + len(block) - 1
            resp = gc._request(
                "PUT",
                url,
                headers={
                    "Content-Length": str(len(block)),
                    "Content-Range": f"bytes {sent}-{end}/{source.size}",
                },
                content=block,
                label="upload-session",
            )
            digest.update(block)
            sent += len(block)
            if sent == source.size:
                item = resp.json()
    except Exception:
        _cancel(gc, url)
        raise
    if sent != source.size:
        _cancel(gc, url)
        return None, "source_size_mismatch", digest.hexdigest()
    return item, "", digest.hexdigest()


def _cancel(gc, url: str) -> None:
    try:
        gc._request("DELETE", url, headers={}, label="upload-session-cancel")
    except Exception:
        pass


def store(
    gc,
    source: Source,
    folder_path: str,
    drive_id: str = "",
    on_conflict: str = "skip",
) -> dict:
    name = safe_filename(source.name)
    folder_path = "/".join(safe_filename(s) for s in folder_path.strip("/").split("/") if s)
    try:
        folders = ensure_folder(gc, drive_id, folder_path)
        folder_info = {
            "folder_web_url": folders[-1]["web_url"] if folders else "",
            "folders": folders,
        }
        try:
            found = gc.get(_item_path(drive_id, folder_path, name))
        except Exception as e:
            if _status(e) != 404:
                raise
            found = None
        if found:
            if on_conflict == "fail":
                return _result("error", error="already_exists", **_existing(found, drive_id))
            return _existing_result(found, source, drive_id, folder_info)
        try:
            if source.size <= SIMPLE_UPLOAD_MAX:
                item, err, sha = _upload_small(gc, source, drive_id, folder_path, name)
            else:
                item, err, sha = _upload_large(gc, source, drive_id, folder_path, name)
        except Exception as e:
            if _status(e) == 409:
                found = gc.get(_item_path(drive_id, folder_path, name))
                return _existing_result(found, source, drive_id, folder_info)
            raise
    except Exception as e:
        return _result("error", error="transfer_failed", detail=str(e)[:300], name=name)
    if err:
        return _result("error", error=err, name=name)
    if (item or {}).get("size") != source.size:
        return _result(
            "error",
            error="size_mismatch",
            name=name,
            expected_size=source.size,
            reported_size=(item or {}).get("size"),
            hint="The stored file does not match the source size. Do not report it as saved.",
        )
    return _result(
        "saved",
        sha256=sha,
        **{**_existing(item, drive_id), "size": source.size},
        **folder_info,
    )
