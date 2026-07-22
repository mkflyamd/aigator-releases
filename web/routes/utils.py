"""Utility routes — delta reset, native file picker, temp file upload."""

import asyncio
import os
import pathlib
import re
import subprocess
import sys

from fastapi import APIRouter, UploadFile
from pydantic import BaseModel

import shared
from proc_utils import no_window_kwargs

router = APIRouter()


# ── Delta Sync Reset ─────────────────────────────────────────────────────────

@router.post("/api/delta/reset")
async def tp_delta_reset(type: str = "all"):
    """Clear delta sync state, forcing next request to do a full re-sync."""
    if type == "all":
        shared._delta_state.clear()
        shared._delta_unsupported.clear()
        shared._save_delta_unsupported()
    else:
        shared._delta_state.pop(type, None)
        shared._delta_unsupported.discard(type)
        shared._save_delta_unsupported()
    return {"ok": True}


# ── Native File Picker ────────────────────────────────────────────────────────

class FilePickerRequest(BaseModel):
    title: str = "Select a file"
    filetypes: str = "All files (*.*)|*.*"  # "Excel (*.xlsx)|*.xlsx|Word (*.docx)|*.docx"
    save: bool = False  # True for "Save As" dialog


def _open_file_dialog(title: str, filetypes: str, save: bool) -> str:
    try:
        import win32ui
        import win32con
        flags = win32con.OFN_OVERWRITEPROMPT if save else win32con.OFN_FILEMUSTEXIST
        # Parse filetypes: "Excel (*.xlsx)|*.xlsx|Word (*.docx)|*.docx"
        dlg = win32ui.CreateFileDialog(not save, None, None, flags, filetypes)
        dlg.SetOFNTitle(title)
        if dlg.DoModal() == 1:  # IDOK
            return dlg.GetPathName()
        return ""
    except ImportError:
        # Fallback to tkinter
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            if save:
                path = filedialog.asksaveasfilename(title=title)
            else:
                path = filedialog.askopenfilename(title=title)
            root.destroy()
            return path or ""
        except Exception:
            return ""


@router.post("/api/file-picker")
async def file_picker(req: FilePickerRequest):
    """Open a native Windows file dialog and return the selected path."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _open_file_dialog, req.title, req.filetypes, req.save)
    if not result:
        return {"ok": False, "message": "No file selected"}
    return {"ok": True, "file_path": result}


def warmup_native_dialogs() -> None:
    """Pay tkinter's cold-import + first Tk() init cost once at server startup
    instead of on the user's first folder/file-picker click. Measured up to
    ~4s cold (import + first window creation, worse under real-time AV
    scanning) - long enough that the first real picker request can outlast a
    keep-alive timeout and drop the connection before its response lands,
    which looks like a failure even though the backend call itself succeeds
    a moment later. Safe to call from a background thread; swallows failures
    since this is best-effort warmup, not a real dialog."""
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.destroy()
    except Exception:
        pass


def _open_directory_dialog(title: str) -> str:
    """Open a native directory picker dialog. Returns selected path or empty string."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        path = filedialog.askdirectory(title=title)
        root.destroy()
        return path or ""
    except Exception:
        return ""


@router.post("/api/directory-picker")
async def directory_picker(title: str = "Select a folder"):
    """Open a native directory picker dialog and return the selected folder path."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _open_directory_dialog, title)
    if not result:
        return {"ok": False, "message": "No folder selected"}
    # Normalise to OS path separators
    result = str(pathlib.Path(result))
    return {"ok": True, "folder_path": result}


# ── Temp File Upload ─────────────────────────────────────────────────────────

@router.post("/api/file-upload-temp")
async def file_upload_temp(file: UploadFile):
    """Save an uploaded document to the user's Downloads folder and return the path."""
    from pathlib import Path
    downloads = Path.home() / "Downloads"
    downloads.mkdir(exist_ok=True)
    dest = downloads / file.filename
    # Avoid overwriting — append a counter if the file already exists
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        i = 1
        while dest.exists():
            dest = downloads / f"{stem} ({i}){suffix}"
            i += 1
    content = await file.read()
    dest.write_bytes(content)
    return {"ok": True, "file_path": str(dest), "file_name": file.filename}


@router.post("/api/image-upload-temp")
async def image_upload_temp(file: UploadFile):
    """Save an uploaded image to ~/Pictures/AIGator/uploads/ so the AI can locate it on disk.

    Returns the absolute saved path which the frontend includes in the chat payload
    (image_paths) so chat.py can surface it to the model. Fixes issue #12.
    """
    from pathlib import Path
    import datetime as _dt
    target = Path.home() / "Pictures" / "AIGator" / "uploads"
    target.mkdir(parents=True, exist_ok=True)
    # Always timestamp-prefix to avoid collisions and preserve upload order
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_name = (file.filename or "image.png").replace("\\", "_").replace("/", "_")
    dest = target / f"{ts}_{safe_name}"
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        i = 1
        while dest.exists():
            dest = target / f"{stem} ({i}){suffix}"
            i += 1
    content = await file.read()
    dest.write_bytes(content)
    return {"ok": True, "file_path": str(dest), "file_name": file.filename}


# ── Open Local File ──────────────────────────────────────────────────────────

class OpenFileRequest(BaseModel):
    path: str


BLOCKED_EXTENSIONS = {'.exe', '.bat', '.cmd', '.ps1', '.vbs', '.msi', '.com', '.scr', '.pif', '.cpl'}


def _do_open_file(path: str, is_dir: bool = False) -> None:
    """Open a file in its default app, or reveal a folder in the OS file manager.

    For directories we invoke the file manager explicitly rather than rely on
    os.startfile()'s ambiguous folder handling, which could fail silently."""
    if is_dir:
        if sys.platform == "win32":
            subprocess.run(["explorer", os.path.normpath(path)], **no_window_kwargs())
            return
        if sys.platform == "darwin":
            subprocess.run(["open", path])
            return
        subprocess.run(["xdg-open", path])
        return
    os.startfile(path)


def _path_normalise(s: str) -> str:
    """Collapse spaces/underscores and strip spaces around punctuation for fuzzy path matching."""
    s = re.sub(r'[ _]+', ' ', s)
    s = re.sub(r'\s*([.\-])\s*', r'\1', s)
    return s


def _fuzzy_resolve_path(p: pathlib.Path) -> pathlib.Path | None:
    """Try to find the real path when the LLM emitted underscores instead of spaces
    (or vice versa) in any path component. Walks each component bottom-up and does
    a case-insensitive, normalised-name scan. Returns the resolved Path on success."""
    parts = p.parts
    resolved = pathlib.Path(parts[0])
    for component in parts[1:]:
        candidate = resolved / component
        if candidate.exists():
            resolved = candidate
            continue
        try:
            siblings = list(resolved.iterdir())
        except (PermissionError, OSError):
            return None
        needle_norm = _path_normalise(component.lower())
        match = next(
            (s for s in siblings if _path_normalise(s.name.lower()) == needle_norm),
            None
        )
        if match is None:
            return None
        resolved = match
    return resolved if resolved.exists() else None


@router.post("/api/open-file")
async def open_file(req: OpenFileRequest):
    """Open a local file (default app) or folder (Explorer/Finder).

    Returns a machine-readable `reason` on failure so the UI can show calm,
    specific copy instead of a silent dead click:
      - blocked   : extension is on the deny-list
      - not_found : path no longer exists
      - error     : the OS open call raised
    """
    p = pathlib.Path(req.path)
    if p.is_file() and p.suffix.lower() in BLOCKED_EXTENSIONS:
        return {"ok": False, "reason": "blocked",
                "message": f"Opening this file type isn't allowed: {p.suffix}"}
    if not p.exists():
        # The AI sometimes writes underscores instead of spaces (or vice versa).
        # Try to find the real file before giving up.
        resolved = await asyncio.get_event_loop().run_in_executor(None, _fuzzy_resolve_path, p)
        if resolved is None:
            return {"ok": False, "reason": "not_found",
                    "message": f"That path no longer exists: {req.path}"}
        p = resolved
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _do_open_file, str(p), p.is_dir())
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": "error", "message": str(e)}


# ── Storage (Gator working files) ─────────────────────────────────────────────

def _dir_size_bytes(path: pathlib.Path) -> int:
    """Total size of a directory tree in bytes. Missing dir → 0."""
    total = 0
    if not path.is_dir():
        return 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                continue
    return total


def _storage_targets() -> dict:
    """The Gator-managed dirs we expose in Settings → Storage.
    `clearable` marks scratch dirs safe to wipe; outputs holds deliverables."""
    from config import WORK_DIR, OUTPUTS_DIR
    return {
        "work": {"path": WORK_DIR, "label": "Workshop (build scratch)", "clearable": True},
        "outputs": {"path": OUTPUTS_DIR, "label": "Generated files", "clearable": False},
    }


@router.get("/api/storage/usage")
async def storage_usage():
    """Report size of each Gator-managed working dir, for Settings → Storage."""
    loop = asyncio.get_event_loop()
    targets = _storage_targets()
    out = []
    for key, t in targets.items():
        size = await loop.run_in_executor(None, _dir_size_bytes, t["path"])
        out.append({
            "key": key,
            "label": t["label"],
            "path": str(t["path"]),
            "size_bytes": size,
            "clearable": t["clearable"],
            "exists": t["path"].is_dir(),
        })
    return {"ok": True, "items": out}


class ClearStorageRequest(BaseModel):
    key: str


def _clear_dir_contents(path: pathlib.Path) -> None:
    """Remove everything inside `path`, keeping the dir itself."""
    import shutil
    if not path.is_dir():
        return
    for entry in path.iterdir():
        try:
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
        except OSError:
            continue


@router.post("/api/storage/clear")
async def storage_clear(req: ClearStorageRequest):
    """Empty a clearable Gator working dir (currently: the build scratch 'work')."""
    targets = _storage_targets()
    t = targets.get(req.key)
    if t is None:
        return {"ok": False, "message": f"Unknown storage target: {req.key}"}
    if not t["clearable"]:
        return {"ok": False, "message": f"'{req.key}' is not clearable from here."}
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _clear_dir_contents, t["path"])
    freed = await loop.run_in_executor(None, _dir_size_bytes, t["path"])
    return {"ok": True, "size_bytes": freed}
