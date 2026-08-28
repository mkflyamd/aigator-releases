"""Screen recorder endpoints — start/stop/pause/resume/status/screens."""
import asyncio
import json
import os
import shutil
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter()

OUT_DIR = Path.home() / "Downloads" / "gator_demos"

# ── Pending notification — HUD posts here after Stop, frontend polls and injects ─
_pending_notification: dict | None = None


# ── ffmpeg discovery ──────────────────────────────────────────────────────────

def _find_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    if os.name == "nt":
        winget_base = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
        if winget_base.exists():
            for candidate in sorted(winget_base.glob("*/*/bin/ffmpeg.exe"), reverse=True):
                if candidate.exists():
                    bin_dir = str(candidate.parent)
                    os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + bin_dir
                    return str(candidate)
        for p in [
            Path("C:/ffmpeg/bin/ffmpeg.exe"),
            Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
            Path.home() / "ffmpeg/bin/ffmpeg.exe",
            Path.home() / "scoop/apps/ffmpeg/current/bin/ffmpeg.exe",
        ]:
            if p.exists():
                return str(p)
    for p in [Path("/usr/local/bin/ffmpeg"), Path("/opt/homebrew/bin/ffmpeg"), Path("/usr/bin/ffmpeg")]:
        if p.exists():
            return str(p)
    return None


def _try_install_ffmpeg() -> str | None:
    """Attempt silent winget install on Windows. Returns path if successful."""
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(
            ["winget", "install", "--id=Gyan.FFmpeg", "-e",
             "--accept-source-agreements", "--accept-package-agreements",
             "--disable-interactivity"],
            capture_output=True, timeout=120,
        )
        if result.returncode == 0:
            return _find_ffmpeg()
    except Exception:
        pass
    return None


_FFMPEG: str | None = _find_ffmpeg()


# ── Session state ─────────────────────────────────────────────────────────────

_ffmpeg_proc: subprocess.Popen | None = None
_recording_path: Path | None = None       # current segment
_recording_start: float | None = None
_paused_at: float | None = None
_paused_elapsed: float = 0.0              # accumulated time before pauses
_segments: list[Path] = []                # all segments for stitching
_session_dir: Path | None = None
_session_tag: str | None = None


def _elapsed() -> float:
    if _recording_start is None:
        return round(_paused_elapsed, 1)
    if _paused_at is not None:
        return round(_paused_elapsed + (_paused_at - _recording_start), 1)
    return round(_paused_elapsed + (time.monotonic() - _recording_start), 1)


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


# ── Screen enumeration ────────────────────────────────────────────────────────

def _list_screens_windows() -> list[dict]:
    """Use ctypes to enumerate monitors on Windows."""
    try:
        import ctypes

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        user32 = ctypes.windll.user32
        screens = []

        # RECT must be defined before WINFUNCTYPE so the pointer type is correct
        MonitorEnumProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_ulong, ctypes.c_ulong,
            ctypes.POINTER(RECT), ctypes.c_double,
        )

        def _cb(hMonitor, hdcMonitor, lprcMonitor, dwData):
            r = lprcMonitor.contents
            screens.append({
                "index": len(screens),
                "x": r.left, "y": r.top,
                "width": r.right - r.left,
                "height": r.bottom - r.top,
                "label": f"Display {len(screens) + 1} ({r.right - r.left}x{r.bottom - r.top})",
                "primary": r.left == 0 and r.top == 0,
            })
            return True

        MonitorEnumProcInst = MonitorEnumProc(_cb)
        user32.EnumDisplayMonitors(None, None, MonitorEnumProcInst, 0)
        return screens
    except Exception:
        return [{"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080,
                 "label": "Display 1 (1920×1080)", "primary": True}]


def _list_screens_mac() -> list[dict]:
    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType", "-json"],
            capture_output=True, text=True, timeout=5
        )
        data = json.loads(result.stdout)
        screens = []
        for i, d in enumerate(data.get("SPDisplaysDataType", [])):
            for res in d.get("spdisplays_ndrvs", []):
                size = res.get("_spdisplays_resolution", "1920 x 1080").replace(" x ", "×")
                screens.append({"index": i, "x": 0, "y": 0,
                                 "width": 1920, "height": 1080,
                                 "label": f"Display {i+1} ({size})", "primary": i == 0})
        return screens or [{"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080,
                            "label": "Display 1", "primary": True}]
    except Exception:
        return [{"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080,
                 "label": "Display 1", "primary": True}]


@router.get("/api/recorder/screens")
async def recorder_screens():
    if os.name == "nt":
        screens = await asyncio.to_thread(_list_screens_windows)
    elif os.path.exists("/usr/bin/xrandr") or os.path.exists("/usr/local/bin/xrandr"):
        screens = [{"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080,
                    "label": "Display 1", "primary": True}]
    else:
        screens = await asyncio.to_thread(_list_screens_mac)
    return {"screens": screens}


# ── Region picker — spawns a fullscreen drag-to-select overlay ───────────────

def _pick_region_tkinter(screen: dict) -> dict | None:
    """Spawn a transparent fullscreen tkinter window on the given screen.
    User drags to select a region. Returns {x, y, w, h} relative to screen,
    or None if cancelled (Escape / no drag).
    Works on Windows and macOS. Runs in a thread (tkinter must be on main thread
    on macOS — on Windows any thread is fine).
    """
    try:
        import tkinter as tk
        result = {}

        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.25)
        root.configure(bg="black")
        root.geometry(f"{screen['width']}x{screen['height']}+{screen['x']}+{screen['y']}")

        canvas = tk.Canvas(root, cursor="cross", bg="black", highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        label = tk.Label(root, text="  Drag to select region — Esc to cancel  ",
                         fg="#f97316", bg="#0a0f1a", font=("system", 11, "bold"),
                         relief="flat", padx=8, pady=4)
        label.place(relx=0.5, rely=0.02, anchor="n")

        state = {"sx": 0, "sy": 0, "rect": None, "size_label": None}

        def on_press(e):
            state["sx"], state["sy"] = e.x, e.y
            if state["rect"]:
                canvas.delete(state["rect"])
            if state["size_label"]:
                canvas.delete(state["size_label"])

        def on_drag(e):
            if state["rect"]:
                canvas.delete(state["rect"])
            if state["size_label"]:
                canvas.delete(state["size_label"])
            x1, y1 = min(state["sx"], e.x), min(state["sy"], e.y)
            x2, y2 = max(state["sx"], e.x), max(state["sy"], e.y)
            state["rect"] = canvas.create_rectangle(
                x1, y1, x2, y2,
                outline="#f97316", width=2, fill="#f9731622",
            )
            # Size label shown near cursor
            w, h = x2 - x1, y2 - y1
            lx = e.x + 8 if e.x + 80 < screen["width"] else e.x - 80
            ly = e.y + 8 if e.y + 20 < screen["height"] else e.y - 22
            state["size_label"] = canvas.create_text(
                lx, ly, text=f"{w}×{h}",
                fill="#f97316", font=("system", 10, "bold"), anchor="nw",
            )

        def on_release(e):
            x1, y1 = min(state["sx"], e.x), min(state["sy"], e.y)
            x2, y2 = max(state["sx"], e.x), max(state["sy"], e.y)
            w, h = x2 - x1, y2 - y1
            if w > 10 and h > 10:
                result["x"] = x1 + screen["x"]
                result["y"] = y1 + screen["y"]
                result["w"] = w
                result["h"] = h
                result["screen_x"] = x1
                result["screen_y"] = y1
            root.destroy()

        def on_escape(e):
            root.destroy()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        root.bind("<Escape>", on_escape)
        root.focus_force()
        root.mainloop()
        return result if result else None
    except Exception as exc:
        return {"error": str(exc)}


@router.post("/api/recorder/pick-region")
async def recorder_pick_region(body: dict = Body(default={})):
    """Spawn a fullscreen overlay on the given screen for the user to drag-select
    a crop region. Returns {x, y, w, h} in screen coordinates."""
    screen_index = (body or {}).get("screen_index", 0)
    if os.name == "nt":
        screens = await asyncio.to_thread(_list_screens_windows)
    else:
        screens = await asyncio.to_thread(_list_screens_mac)
    screen = screens[screen_index] if screen_index < len(screens) else screens[0]
    region = await asyncio.to_thread(_pick_region_tkinter, screen)
    if not region:
        return {"ok": False, "cancelled": True}
    if "error" in region:
        return JSONResponse(status_code=500, content={"ok": False, "error": region["error"]})
    return {
        "ok": True,
        "x": region["x"], "y": region["y"],
        "w": region["w"], "h": region["h"],
        "screen_x": region.get("screen_x", region["x"]),
        "screen_y": region.get("screen_y", region["y"]),
        "label": f"{region['w']}×{region['h']} at ({region['x']},{region['y']})",
    }


# ── Start ─────────────────────────────────────────────────────────────────────

class StartRequest(BaseModel):
    screen_index: int = 0
    crop_x: Optional[int] = None
    crop_y: Optional[int] = None
    crop_w: Optional[int] = None
    crop_h: Optional[int] = None
    framerate: int = 30
    force: bool = False  # if True, stop any existing recording first


def _build_ffmpeg_cmd(ffmpeg: str, out_path: Path, req: StartRequest,
                      screens: list[dict]) -> list[str]:
    screen = screens[req.screen_index] if req.screen_index < len(screens) else screens[0]

    if os.name == "nt":
        # gdigrab: offset selects screen, size crops region
        ox = screen["x"] + (req.crop_x or 0)
        oy = screen["y"] + (req.crop_y or 0)
        ow = req.crop_w or screen["width"]
        oh = req.crop_h or screen["height"]
        cmd = [
            ffmpeg, "-y",
            "-f", "gdigrab",
            "-framerate", str(req.framerate),
            "-offset_x", str(ox),
            "-offset_y", str(oy),
            "-video_size", f"{ow}x{oh}",
            "-i", "desktop",
            "-vcodec", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            str(out_path),
        ]
    else:
        # avfoundation (macOS) or x11grab (Linux)
        if os.path.exists("/usr/bin/xrandr"):
            display = os.environ.get("DISPLAY", ":0")
            ox = screen["x"] + (req.crop_x or 0)
            oy = screen["y"] + (req.crop_y or 0)
            ow = req.crop_w or screen["width"]
            oh = req.crop_h or screen["height"]
            cmd = [
                ffmpeg, "-y",
                "-f", "x11grab",
                "-framerate", str(req.framerate),
                "-video_size", f"{ow}x{oh}",
                "-i", f"{display}+{ox},{oy}",
                "-vcodec", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                str(out_path),
            ]
        else:
            cmd = [
                ffmpeg, "-y",
                "-f", "avfoundation",
                "-framerate", str(req.framerate),
                "-capture_screen_index", str(req.screen_index),
                "-i", f"{req.screen_index}:none",
                "-vcodec", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                str(out_path),
            ]
    return cmd


def _start_segment(ffmpeg: str, req: StartRequest, screens: list[dict],
                    seg_index: int) -> tuple[subprocess.Popen, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    seg_path = _session_dir / f"seg_{seg_index:02d}.mp4"
    log_path = _session_dir / "ffmpeg_log.txt"
    cmd = _build_ffmpeg_cmd(ffmpeg, seg_path, req, screens)
    log_handle = open(log_path, "ab")
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
    finally:
        log_handle.close()
    return proc, seg_path


@router.post("/api/recorder/start")
async def recorder_start(req: StartRequest = StartRequest()):
    global _ffmpeg_proc, _recording_path, _recording_start
    global _paused_at, _paused_elapsed, _segments, _session_dir, _session_tag

    if _ffmpeg_proc is not None and _ffmpeg_proc.poll() is None:
        if not req.force:
            return {"ok": False, "error": "Already recording", "status": "recording",
                    "path": str(_recording_path), "elapsed": _elapsed()}
        # force=True — stop the stale recording silently before starting fresh
        try:
            if os.name == "nt":
                _ffmpeg_proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                _ffmpeg_proc.terminate()
            _ffmpeg_proc.wait(timeout=5)
        except Exception:
            pass
        _ffmpeg_proc = None
        _recording_start = None
        _paused_at = None
        _paused_elapsed = 0.0

    ffmpeg = _FFMPEG or _find_ffmpeg()
    if not ffmpeg:
        # Try silent runtime install via winget before giving up
        ffmpeg = _try_install_ffmpeg()
    if not ffmpeg:
        return JSONResponse(status_code=500, content={
            "ok": False,
            "error": (
                "ffmpeg not found. "
                "Install it and restart Gator: "
                "Windows: winget install Gyan.FFmpeg  |  "
                "macOS: brew install ffmpeg  |  "
                "Linux: sudo apt install ffmpeg"
            ),
        })

    screens = _list_screens_windows() if os.name == "nt" else _list_screens_mac()

    _session_tag = datetime.now().strftime("demo_%Y%m%d_%H%M%S")
    _session_dir = OUT_DIR / _session_tag
    _session_dir.mkdir(parents=True, exist_ok=True)
    _segments = []
    _paused_elapsed = 0.0
    _paused_at = None

    try:
        proc, seg_path = _start_segment(ffmpeg, req, screens, 0)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})

    _ffmpeg_proc = proc
    _recording_path = seg_path
    _recording_start = time.monotonic()
    _segments.append(seg_path)

    await asyncio.sleep(0.6)
    if _ffmpeg_proc.poll() is not None:
        return JSONResponse(status_code=500, content={
            "ok": False,
            "error": "ffmpeg exited immediately — check ffmpeg_log.txt",
            "log": str(_session_dir / "ffmpeg_log.txt"),
        })

    screen = screens[req.screen_index] if req.screen_index < len(screens) else screens[0]
    return {
        "ok": True, "status": "recording",
        "path": str(_session_dir / f"{_session_tag}_final.mp4"),
        "session_dir": str(_session_dir),
        "pid": _ffmpeg_proc.pid,
        "elapsed": 0,
        "screen": screen["label"],
        "crop": {"x": req.crop_x, "y": req.crop_y, "w": req.crop_w, "h": req.crop_h}
                if any(v is not None for v in [req.crop_x, req.crop_y, req.crop_w, req.crop_h]) else None,
    }


# ── Pause ─────────────────────────────────────────────────────────────────────

@router.post("/api/recorder/pause")
async def recorder_pause():
    global _ffmpeg_proc, _paused_at, _paused_elapsed, _recording_start

    if _ffmpeg_proc is None or _ffmpeg_proc.poll() is not None:
        return {"ok": False, "error": "Not recording"}
    if _paused_at is not None:
        return {"ok": False, "error": "Already paused"}

    # Windows: can't SIGSTOP ffmpeg — stop the segment cleanly
    elapsed_so_far = _elapsed()
    try:
        if os.name == "nt":
            _ffmpeg_proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            _ffmpeg_proc.send_signal(signal.SIGSTOP)
    except Exception:
        pass

    if os.name == "nt":
        try:
            _ffmpeg_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _ffmpeg_proc.kill()
        _ffmpeg_proc = None

    _paused_elapsed = elapsed_so_far
    _paused_at = time.monotonic()
    _recording_start = None

    return {"ok": True, "status": "paused", "elapsed": elapsed_so_far}


# ── Resume ────────────────────────────────────────────────────────────────────

_last_start_req: StartRequest = StartRequest()


@router.post("/api/recorder/resume")
async def recorder_resume():
    global _ffmpeg_proc, _recording_path, _recording_start, _paused_at, _segments

    if _paused_at is None:
        return {"ok": False, "error": "Not paused"}

    ffmpeg = _FFMPEG or _find_ffmpeg()
    if not ffmpeg:
        return JSONResponse(status_code=500, content={"ok": False, "error": "ffmpeg not found"})

    if os.name == "nt":
        screens = _list_screens_windows()
        seg_index = len(_segments)
        try:
            proc, seg_path = _start_segment(ffmpeg, _last_start_req, screens, seg_index)
        except Exception as exc:
            return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})
        _ffmpeg_proc = proc
        _recording_path = seg_path
        _segments.append(seg_path)
        await asyncio.sleep(0.4)
        if _ffmpeg_proc.poll() is not None:
            return JSONResponse(status_code=500, content={"ok": False, "error": "ffmpeg failed to restart"})
    else:
        # POSIX: resume the stopped process
        try:
            _ffmpeg_proc.send_signal(signal.SIGCONT)
        except Exception as exc:
            return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})

    _recording_start = time.monotonic()
    _paused_at = None

    return {"ok": True, "status": "recording", "elapsed": _paused_elapsed}


# ── Stop ──────────────────────────────────────────────────────────────────────

def _stitch_segments(ffmpeg: str, segments: list[Path], out_path: Path) -> Path:
    if len(segments) == 1:
        import shutil as _sh
        _sh.copy2(segments[0], out_path)
        return out_path
    concat_file = out_path.parent / "concat_list.txt"
    with open(concat_file, "w") as f:
        for s in segments:
            f.write(f"file '{s}'\n")
    subprocess.run(
        [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
         "-c", "copy", str(out_path)],
        check=True, capture_output=True,
    )
    concat_file.unlink(missing_ok=True)
    return out_path


@router.post("/api/recorder/stop")
async def recorder_stop():
    global _ffmpeg_proc, _recording_path, _recording_start
    global _paused_at, _paused_elapsed, _segments, _session_dir, _session_tag

    was_paused = _paused_at is not None

    if not was_paused:
        if _ffmpeg_proc is None or _ffmpeg_proc.poll() is not None:
            _ffmpeg_proc = None
            return {"ok": False, "error": "Not recording", "status": "idle"}
        elapsed = _elapsed()
        try:
            if os.name == "nt":
                _ffmpeg_proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                _ffmpeg_proc.terminate()
            try:
                _ffmpeg_proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                _ffmpeg_proc.kill()
        except Exception:
            pass
        _ffmpeg_proc = None
        _recording_start = None
    else:
        elapsed = _paused_elapsed

    await asyncio.sleep(0.5)

    ffmpeg = _FFMPEG or _find_ffmpeg()
    final_path = _session_dir / f"{_session_tag}_final.mp4"

    try:
        final = await asyncio.to_thread(_stitch_segments, ffmpeg, _segments, final_path)
        size = _file_size(final)
    except Exception as exc:
        # fallback: return last segment
        final = _segments[-1] if _segments else _recording_path
        size = _file_size(final) if final else 0

    _paused_at = None
    _paused_elapsed = 0.0

    return {
        "ok": True, "status": "idle",
        "path": str(final) if final else None,
        "size_bytes": size,
        "elapsed": elapsed,
        "segments": len(_segments),
    }


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/api/recorder/status")
async def recorder_status():
    global _ffmpeg_proc
    ffmpeg = _FFMPEG or _find_ffmpeg()

    if _paused_at is not None:
        return {
            "status": "paused", "elapsed": _elapsed(), "size_bytes": 0,
            "path": str(_session_dir / f"{_session_tag}_final.mp4") if _session_dir else None,
            "ffmpeg": bool(ffmpeg), "segments": len(_segments),
        }

    if _ffmpeg_proc is None or _ffmpeg_proc.poll() is not None:
        _ffmpeg_proc = None
        return {
            "status": "idle", "elapsed": 0, "size_bytes": 0, "path": None,
            "ffmpeg": bool(ffmpeg), "ffmpeg_path": ffmpeg,
        }

    size = _file_size(_recording_path) if _recording_path else 0
    return {
        "status": "recording", "elapsed": _elapsed(), "size_bytes": size,
        "path": str(_session_dir / f"{_session_tag}_final.mp4") if _session_dir else None,
        "pid": _ffmpeg_proc.pid,
        "ffmpeg": True, "segments": len(_segments),
    }


# ── Notify — HUD posts completion message here; frontend polls and injects ────

class NotifyRequest(BaseModel):
    message: str
    context_id: str = "default"


@router.post("/api/recorder/notify")
async def recorder_notify(req: NotifyRequest):
    """Called by the HUD widget after Stop to inject a message into the Gator chat.
    The frontend polls GET /api/recorder/pending and fires the message."""
    global _pending_notification
    _pending_notification = {"message": req.message, "context_id": req.context_id}
    return {"ok": True}


@router.get("/api/recorder/pending")
async def recorder_pending():
    """Frontend polls this every 2s. Returns and clears any pending notification."""
    global _pending_notification
    if _pending_notification:
        msg = _pending_notification
        _pending_notification = None
        return {"ok": True, "pending": True, "message": msg["message"], "context_id": msg["context_id"]}
    return {"ok": True, "pending": False}
