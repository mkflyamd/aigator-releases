"""Provider-neutral file transfer: move or copy a file into a folder, riding out locks.

A provider is any object with stat, is_foreign_owner, move, copy, find_in_folder,
download and upload (see tests/test_files_transfer_core.py for the exact shapes).
Nothing here deletes anything: when a move is impossible the original stays and the
result says so.
"""

import time
from pathlib import Path

LOCK_RETRY_DELAYS = (3, 6)
_NO_FALLBACK = ("forbidden", "not_found", "conflict", "throttled")


def _result(status, method=None, original_remains=True, reason=None, dest=None, local_copy=None, **extra):
    return {
        "status": status,
        "method": method,
        "original_remains": original_remains,
        "reason": reason,
        "dest": dest,
        "local_copy": local_copy,
        **extra,
    }


def _failed(error, error_code="unknown", reason=None, local_copy=None):
    return _result(
        "failed",
        reason=reason,
        local_copy=local_copy,
        error=error,
        error_code=error_code,
        message=f"The file was not transferred: {error}",
    )


def _dest(d):
    return {
        "drive_id": d.get("drive_id", ""),
        "item_id": d.get("item_id", ""),
        "name": d.get("name", ""),
        "web_url": d.get("web_url", ""),
    }


def _copied_message(reason):
    why = {
        "locked": "the file is open or locked, so it could not be moved",
        "not_owner": "the file is in another person's OneDrive, so it was copied rather than moved",
    }.get(reason)
    head = f"Copied to the destination because {why}." if why else "Copied to the destination."
    return head + " The original is still in place. Gator never deletes files, so the user can remove it themselves."


def _found_item(found):
    return isinstance(found, dict) and "error" not in found and bool(found.get("item_id"))


def _safe_local_name(name):
    """Reduce a (possibly LLM-supplied) name to a bare filename with no path parts."""
    leaf = name.replace("\\", "/").split("/")[-1]
    leaf = leaf.replace(":", "").rstrip(". ")
    return leaf or "file"


def _unique_local_path(downloads_dir, name):
    base = Path(downloads_dir)
    candidate = base / _safe_local_name(name)
    stem, suffix, n = candidate.stem, candidate.suffix, 1
    while candidate.exists():
        candidate = base / f"{stem} ({n}){suffix}"
        n += 1
    if candidate.resolve().parent != base.resolve():
        raise ValueError(f"Refusing to write outside {base}: {candidate}")
    return str(candidate)


def _move_with_lock_retry(provider, source, dest_folder, new_name, sleep):
    moved = provider.move(source, dest_folder, new_name)
    for delay in LOCK_RETRY_DELAYS:
        if "error" not in moved or moved.get("error_code") != "locked":
            break
        sleep(delay)
        moved = provider.move(source, dest_folder, new_name)
    return moved


def _copied_dest(provider, copied, dest_folder, name, size):
    item_id = copied.get("item_id")
    drive_id = copied.get("dest_drive_id") or dest_folder["drive_id"]
    if item_id:
        meta = provider.stat({"drive_id": drive_id, "item_id": item_id})
        if "error" not in meta:
            return _dest(meta)
        return {"drive_id": drive_id, "item_id": item_id, "name": name, "web_url": ""}
    found = provider.find_in_folder(dest_folder, name, size)
    return _dest(found) if _found_item(found) else None


def transfer(provider, source, dest_folder, mode="move", new_name="", sleep=time.sleep, downloads_dir=None):
    if mode not in ("move", "copy"):
        return _failed("mode must be 'move' or 'copy'")
    info = provider.stat(source)
    if "error" in info:
        return _failed(info["error"], info.get("error_code", "unknown"))
    name = new_name or info.get("name", "")
    size = info.get("size")

    reason = None
    if mode == "move":
        if provider.is_foreign_owner(source):
            reason = "not_owner"
        else:
            moved = _move_with_lock_retry(provider, source, dest_folder, new_name, sleep)
            if "error" not in moved:
                return _result("moved", "native_move", False, None, _dest(moved), message="Moved. The file is now only at the destination.")
            if moved.get("error_code") != "locked":
                return _failed(moved["error"], moved.get("error_code", "unknown"))
            reason = "locked"

    # Snapshot the destination first: a same-name, same-size file that is already there
    # proves nothing about whether this copy landed.
    existed_before = _found_item(provider.find_in_folder(dest_folder, name, size))
    copied = provider.copy(source, dest_folder, new_name)
    if "error" not in copied:
        if copied.get("status") == "pending":
            found = None if existed_before else provider.find_in_folder(dest_folder, name, size)
            dest = _dest(found) if _found_item(found) else None
        else:
            dest = _copied_dest(provider, copied, dest_folder, name, size)
        if dest:
            return _result("copied", "server_copy", True, reason, dest, message=_copied_message(reason))
        return _result(
            "pending",
            "server_copy",
            True,
            reason,
            monitor_url=copied.get("monitor_url", ""),
            message="The copy is still running in OneDrive. Do not retry it; check the destination folder shortly.",
        )
    if copied.get("error_code") in _NO_FALLBACK:
        return _failed(copied["error"], copied["error_code"], reason)
    if not existed_before:
        # The copy may have finished in OneDrive even though it reported an error.
        found = provider.find_in_folder(dest_folder, name, size)
        if _found_item(found):
            return _result("copied", "server_copy", True, reason, _dest(found), message=_copied_message(reason))

    try:
        local = _unique_local_path(downloads_dir or Path.home() / "Downloads", name)
    except ValueError as e:
        return _failed(str(e), "unknown", reason)
    dl = provider.download(source, local)
    if "error" in dl:
        return _failed(dl["error"], dl.get("error_code", "unknown"), reason)
    up = provider.upload(dl["saved_to"], dest_folder, name)
    if "error" in up:
        return _failed(up["error"], up.get("error_code", "unknown"), reason, local_copy=dl["saved_to"])
    check = provider.stat({"drive_id": up.get("drive_id", ""), "item_id": up.get("item_id", "")})
    if "error" in check or check.get("size") != size:
        why = check.get("error") or f"uploaded size {check.get('size')} does not match original size {size}"
        return _failed(f"Could not verify the uploaded copy: {why}", "verify_failed", reason, local_copy=dl["saved_to"])
    return _result(
        "copied",
        "download_upload",
        True,
        reason,
        _dest(up),
        local_copy=dl["saved_to"],
        message=_copied_message(reason) + f" A local copy is at {dl['saved_to']}.",
    )
