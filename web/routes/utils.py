"""Utility routes — delta reset, native file picker, temp file upload."""

import asyncio
import os
import pathlib

from fastapi import APIRouter, UploadFile
from pydantic import BaseModel

import shared

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


def _do_open_file(path: str) -> None:
    os.startfile(path)


@router.post("/api/open-file")
async def open_file(req: OpenFileRequest):
    """Open a local file path in the default OS application."""
    p = pathlib.Path(req.path)
    if p.suffix.lower() in BLOCKED_EXTENSIONS:
        return {"ok": False, "message": f"Opening this file type is not allowed: {p.suffix}"}
    if not p.exists():
        return {"ok": False, "message": f"File not found: {req.path}"}
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _do_open_file, str(p))
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "message": str(e)}
