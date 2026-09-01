"""Screen recorder endpoints — start/stop/pause/resume/status/screens."""
import asyncio
import atexit
import json
import os
import shutil
import signal
import subprocess
import threading
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
_open_widget_request: bool = False


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


def _find_ffprobe() -> str | None:
    """Find ffprobe alongside ffmpeg — same bin dir, case-insensitive on Windows."""
    ffmpeg = _find_ffmpeg()
    if ffmpeg:
        ffmpeg_path = Path(ffmpeg)
        # Try same directory: ffprobe / ffprobe.exe (case-insensitive glob)
        for candidate in ffmpeg_path.parent.glob("ffprobe*"):
            name_lower = candidate.name.lower()
            if name_lower in ("ffprobe", "ffprobe.exe") and candidate.is_file():
                return str(candidate)
    # Fallback: PATH
    found = shutil.which("ffprobe")
    return found


_FFMPEG: str | None = _find_ffmpeg()
_FFPROBE: str | None = _find_ffprobe()


# ── Session state ─────────────────────────────────────────────────────────────

_ffmpeg_proc: subprocess.Popen | None = None
_recording_path: Path | None = None       # current segment
_recording_start: float | None = None
_paused_at: float | None = None
_paused_elapsed: float = 0.0              # accumulated time before pauses
_segments: list[Path] = []                # all segments for stitching
_session_dir: Path | None = None
_session_tag: str | None = None
_border_threads: "list[tuple[threading.Thread, threading.Event, list]]" = []
_last_screen_index: int = 0  # remembered for global hotkey start
_last_crop: dict | None = None  # remembered for global hotkey start
# Each entry's third element is a 1-item list holding the tkinter root once created,
# so _stop_recording_border can call root.after(0, root.quit) directly.


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
    """Enumerate monitors and return coordinates for gdigrab.

    gdigrab uses the virtual desktop coordinate system as reported by
    EnumDisplayMonitors — these are LOGICAL (DPI-scaled) coordinates on
    Windows with display scaling. The virtual desktop spans all monitors
    in logical space. gdigrab's -offset_x/-offset_y/-video_size must all
    be in this same logical coordinate space.

    We return the raw EnumDisplayMonitors coordinates without scaling.
    The label shows the logical resolution (what gdigrab will capture at).
    """
    try:
        import ctypes

        user32 = ctypes.windll.user32

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        screens = []

        MonitorEnumProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_ulong, ctypes.c_ulong,
            ctypes.POINTER(RECT), ctypes.c_double,
        )

        def _cb(hMonitor, hdcMonitor, lprcMonitor, dwData):
            r = lprcMonitor.contents
            w = r.right - r.left
            h = r.bottom - r.top
            screens.append({
                "index": len(screens),
                "x": r.left, "y": r.top,
                "width": w, "height": h,
                "label": f"Display {len(screens) + 1} ({w}x{h})",
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
    return {"screens": screens, "last_screen_index": _last_screen_index}


@router.post("/api/recorder/select-screen")
async def recorder_select_screen(body: dict = Body(default={})):
    """Widget calls this when user changes the screen dropdown so the backend
    remembers the selection for global hotkey starts."""
    global _last_screen_index, _last_crop
    _last_screen_index = (body or {}).get("screen_index", 0)
    _last_crop = None  # clear crop when screen changes
    return {"ok": True, "screen_index": _last_screen_index}


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
        # Use a dark semi-transparent overlay color instead of window-level alpha.
        # Window alpha fades EVERYTHING including the orange selection rect, making
        # it invisible. Instead: fully opaque window, dark canvas bg simulates the
        # dim overlay, and selection elements draw at 100% opacity so they're vivid.
        root.attributes("-alpha", 0.75)
        root.configure(bg="#000000")
        root.geometry(f"{screen['width']}x{screen['height']}+{screen['x']}+{screen['y']}")

        # Dark semi-transparent canvas — simulates screen dimming
        canvas = tk.Canvas(root, cursor="cross", bg="#0a0a0a", highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        label = tk.Label(root, text="  Drag to select region — Esc to cancel  ",
                         fg="#ffffff", bg="#f97316", font=("system", 11, "bold"),
                         relief="flat", padx=10, pady=5)
        label.place(relx=0.5, rely=0.02, anchor="n")

        state = {"sx": 0, "sy": 0, "rect": None, "size_label": None}

        def _clear_drag():
            if state["rect"]:
                canvas.delete(state["rect"])
                state["rect"] = None
            if state["size_label"]:
                canvas.delete(state["size_label"])
                state["size_label"] = None

        def on_press(e):
            state["sx"], state["sy"] = e.x, e.y
            _clear_drag()

        def on_drag(e):
            _clear_drag()
            x1, y1 = min(state["sx"], e.x), min(state["sy"], e.y)
            x2, y2 = max(state["sx"], e.x), max(state["sy"], e.y)
            w, h = x2 - x1, y2 - y1
            # Selection rectangle — bright orange, fully visible
            state["rect"] = canvas.create_rectangle(
                x1, y1, x2, y2,
                outline="#f97316", width=3, fill="#1a0a00",
            )
            # Size label near cursor
            lx = e.x + 10 if e.x + 90 < screen["width"] else e.x - 90
            ly = e.y + 10 if e.y + 24 < screen["height"] else e.y - 28
            state["size_label"] = canvas.create_text(
                lx, ly, text=f"{w} × {h}",
                fill="#f97316", font=("system", 11, "bold"), anchor="nw",
            )

        def on_release(e):
            x1, y1 = min(state["sx"], e.x), min(state["sy"], e.y)
            x2, y2 = max(state["sx"], e.x), max(state["sy"], e.y)
            w, h = x2 - x1, y2 - y1
            if w <= 10 or h <= 10:
                root.destroy()
                return

            # Store result
            result["x"] = x1 + screen["x"]
            result["y"] = y1 + screen["y"]
            result["w"] = w
            result["h"] = h
            result["screen_x"] = x1
            result["screen_y"] = y1

            # ── Confirmation view ─────────────────────────────────────────────
            _clear_drag()

            # Mask outside the selection with a slightly darker overlay
            sw, sh = screen["width"], screen["height"]
            for rx1, ry1, rx2, ry2 in [
                (0, 0, sw, y1), (0, y2, sw, sh),
                (0, y1, x1, y2), (x2, y1, sw, y2),
            ]:
                if rx2 > rx1 and ry2 > ry1:
                    canvas.create_rectangle(rx1, ry1, rx2, ry2,
                                            fill="#000000", outline="")

            # Bright orange border — 4px so it's clearly visible
            canvas.create_rectangle(x1, y1, x2, y2,
                                    outline="#f97316", width=4, fill="")

            # Corner squares for precision feel (like Figma/Sketch crop handles)
            cs = 10
            for cx, cy in [(x1, y1), (x2 - cs, y1), (x1, y2 - cs), (x2 - cs, y2 - cs)]:
                canvas.create_rectangle(cx, cy, cx + cs, cy + cs,
                                        fill="#f97316", outline="")

            # Confirmation badge centred in the selection
            mid_x, mid_y = (x1 + x2) // 2, (y1 + y2) // 2
            # Badge background
            bw, bh = 160, 36
            canvas.create_rectangle(
                mid_x - bw // 2, mid_y - bh // 2,
                mid_x + bw // 2, mid_y + bh // 2,
                fill="#f97316", outline="", width=0,
            )
            canvas.create_text(
                mid_x, mid_y,
                text=f"✓  {w} × {h}",
                fill="#ffffff", font=("system", 13, "bold"),
                anchor="center",
            )

            label.place_forget()
            canvas.unbind("<B1-Motion>")
            canvas.unbind("<ButtonPress-1>")
            canvas.unbind("<ButtonRelease-1>")
            root.update()

            # Hold the confirmation visible for 900ms then close
            root.after(900, root.destroy)

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


# ── Recording border overlay ──────────────────────────────────────────────────

def _run_recording_border(screen: dict, crop: dict | None, stop_event: threading.Event, root_ref: list):
    """Show a transparent orange border around the capture area while recording.

    Runs in its own thread (tkinter must own its event loop). The window is:
    - Fully transparent interior — only a 4px orange border is visible.
    - Always on top, click-through (WS_EX_TRANSPARENT on Windows).
    - Excluded from screen capture via WDA_EXCLUDEFROMCAPTURE so it never
      appears in the recorded video.
    - Destroyed as soon as stop_event is set (recording stopped/paused).
    """
    root = None
    try:
        import tkinter as tk

        # Border bounds are in logical pixels (same as screen dict — gdigrab
        # and tkinter both use logical/virtual-desktop coordinates).
        if crop:
            bx, by, bw, bh = crop["x"], crop["y"], crop["w"], crop["h"]
        else:
            bx, by, bw, bh = screen["x"], screen["y"], screen["width"], screen["height"]

        BORDER = 4
        root = tk.Tk()
        root_ref.append(root)  # expose to _stop_recording_border for direct quit
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-transparentcolor", "#010101")
        root.configure(bg="#010101")
        root.geometry(f"{bw}x{bh}+{bx}+{by}")
        root.lift()

        canvas = tk.Canvas(root, bg="#010101", highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        # Outer filled rect (transparent interior)
        canvas.create_rectangle(
            0, 0, bw, bh,
            outline="#f97316", width=BORDER, fill="#010101",
        )

        # "REC" badge — bottom-left corner (avoids overlapping HUD titlebar close button)
        # The badge is the ONLY clickable part of the border window. Clicking it
        # opens the recorder widget. The rest of the border is click-through.
        badge_pad = BORDER + 4
        badge_h = 22
        badge_w = 52
        by1 = bh - badge_pad - badge_h
        by2 = bh - badge_pad
        badge_rect = canvas.create_rectangle(
            badge_pad, by1, badge_pad + badge_w, by2,
            fill="#f97316", outline="", width=0,
        )
        canvas.create_oval(
            badge_pad + 5, by1 + 6,
            badge_pad + 14, by1 + 15,
            fill="#ffffff", outline="",
        )
        canvas.create_text(
            badge_pad + 32, by1 + 11,
            text="REC", fill="#ffffff", font=("system", 9, "bold"), anchor="center",
        )
        # Tag the badge items so we can bind click on them
        canvas.itemconfig(badge_rect, tags="rec_badge")

        def _on_badge_click(_event):
            """Click on REC badge → tell frontend to open the widget."""
            try:
                import urllib.request
                urllib.request.urlopen(
                    "http://localhost:8003/api/recorder/open-widget", timeout=2
                )
            except Exception:
                pass

        canvas.tag_bind("rec_badge", "<Button-1>", _on_badge_click)

        if os.name == "nt":
            import ctypes

            # Make window click-through so the user can interact with apps underneath.
            # WS_EX_TRANSPARENT makes the ENTIRE window click-through, but we need
            # the REC badge to be clickable. So we DON'T use WS_EX_TRANSPARENT —
            # instead we use WS_EX_LAYERED with a transparent color key. The
            # transparent interior (#010101) passes clicks through to apps below,
            # while the orange badge is opaque and receives clicks.
            try:
                hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
            except Exception:
                hwnd = root.winfo_id()
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            # WS_EX_LAYERED only (no WS_EX_TRANSPARENT) — transparent color key
            # handles click-through for the #010101 areas, badge stays clickable
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)

            # Exclude from screen capture (WDA_EXCLUDEFROMCAPTURE = 0x11)
            try:
                ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x11)
            except Exception:
                pass

        def _poll():
            if stop_event.is_set():
                try:
                    root.withdraw()  # hide immediately — instant visual removal
                    root.quit()      # exit mainloop cleanly
                except Exception:
                    pass
                return
            try:
                root.after(100, _poll)
            except Exception:
                pass

        root.after(100, _poll)
        root.mainloop()
        # After mainloop exits: withdraw again in case quit() raced with withdraw()
        try:
            root.withdraw()
        except Exception:
            pass
    except Exception:
        pass
    # No destroy() — calling destroy() after mainloop() from the tkinter thread
    # triggers "Tcl_AsyncDelete: async handler deleted by the wrong thread" on
    # Windows/macOS and crashes Tcl, leaving the window visible. withdraw() +
    # quit() is sufficient: the window is hidden and the thread exits cleanly.


def _start_recording_border(screen: dict, crop: dict | None) -> None:
    """Stop any existing border windows, then start exactly one new one."""
    _stop_recording_border()
    stop_event = threading.Event()
    root_ref: list = []
    t = threading.Thread(
        target=_run_recording_border,
        args=(screen, crop, stop_event, root_ref),
        daemon=True,
    )
    t.start()
    _border_threads.append((t, stop_event, root_ref))


def _stop_recording_border() -> None:
    """Signal all border threads to quit immediately."""
    for t, ev, root_ref in _border_threads:
        ev.set()
        # All tkinter calls MUST go through after() — it's the only thread-safe
        # method. But root may already be destroyed or the mainloop may have
        # exited, so wrap in try/except and don't let a failure here crash the
        # process. The stop_event + 100ms poll is the reliable teardown path;
        # after(0, ...) is just an optimization to skip the poll delay.
        if root_ref:
            try:
                root = root_ref[0]
                if root and hasattr(root, 'after') and hasattr(root, 'winfo_exists'):
                    try:
                        if root.winfo_exists():
                            root.after(0, root.withdraw)
                            root.after(0, root.quit)
                    except Exception:
                        pass
            except Exception:
                pass
    still_alive = []
    for t, ev, rr in _border_threads:
        if t.is_alive():
            still_alive.append((t, ev, rr))
        else:
            # Thread exited — clear root_ref so the Tk object can be GC'd
            if rr:
                rr.clear()
    _border_threads.clear()
    _border_threads.extend(still_alive)


atexit.register(_stop_recording_border)


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
        # gdigrab always operates in physical pixels regardless of the calling
        # process's DPI awareness. Python's ctypes/GetSystemMetrics return
        # LOGICAL coordinates when the process is DPI-unaware, which differ
        # from physical pixels on scaled displays (e.g. 1280x800 logical on a
        # 1920x1200 physical 150%-scaled screen). Passing logical dimensions as
        # -video_size causes gdigrab to capture only a fraction of the screen.
        #
        # Fix: omit -offset_x/-offset_y/-video_size for full-screen capture so
        # gdigrab auto-detects the correct physical desktop dimensions. Only add
        # these flags when a crop region is explicitly requested.
        has_crop = any(v is not None for v in [req.crop_x, req.crop_y, req.crop_w, req.crop_h])
        cmd = [
            ffmpeg, "-y",
            "-f", "gdigrab",
            "-framerate", str(req.framerate),
        ]
        # Always pass -offset_x/-offset_y/-video_size using PHYSICAL pixel
        # coordinates from _list_screens_windows(). gdigrab works in physical
        # pixels and needs explicit dimensions — omitting -video_size causes it
        # to capture the full virtual desktop instead of just the target monitor.
        ox = screen["x"] + (req.crop_x or 0)
        oy = screen["y"] + (req.crop_y or 0)
        ow = req.crop_w or screen["width"]
        oh = req.crop_h or screen["height"]
        if ox != 0 or oy != 0 or has_crop:
            cmd += ["-offset_x", str(ox), "-offset_y", str(oy),
                    "-video_size", f"{ow}x{oh}"]
        else:
            # Primary monitor, full screen, no crop — still pass video_size so
            # gdigrab encodes at the correct physical resolution rather than
            # defaulting to the virtual desktop size (which may differ on
            # multi-monitor setups).
            cmd += ["-video_size", f"{ow}x{oh}"]
        cmd += [
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
    with open(log_path, "ab") as lf:
        lf.write(f"[cmd seg{seg_index}] {' '.join(str(c) for c in cmd)}\n".encode())
        lf.write(f"[screens] {screens}\n".encode())
        lf.write(f"[req] screen_index={req.screen_index} crop={req.crop_x},{req.crop_y},{req.crop_w},{req.crop_h}\n".encode())
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
    global _last_screen_index, _last_crop

    # Remember the screen selection so global hotkeys (Alt+R) use the same screen
    _last_screen_index = req.screen_index
    _last_crop = {"x": req.crop_x, "y": req.crop_y, "w": req.crop_w, "h": req.crop_h} \
                 if any(v is not None for v in [req.crop_x, req.crop_y, req.crop_w, req.crop_h]) else None

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
    _stop_recording_border()


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
    if not screens:
        screens = [{"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080,
                    "label": "Display 1", "primary": True}]

    # Validate screen index against current connected monitors.
    # If the stored index no longer exists (e.g. monitor unplugged), fall back
    # to the primary screen so recording still works rather than silently failing.
    if req.screen_index >= len(screens):
        req = req.model_copy(update={"screen_index": 0})

    # Validate crop region against the actual screen dimensions.
    # Crop set on a now-disconnected monitor will have out-of-bounds coordinates
    # — clamp them to the current screen and warn rather than crashing ffmpeg.
    screen = screens[req.screen_index]
    sw, sh = screen["width"], screen["height"]
    if any(v is not None for v in [req.crop_x, req.crop_y, req.crop_w, req.crop_h]):
        cx = max(0, min(req.crop_x or 0, sw - 1))
        cy = max(0, min(req.crop_y or 0, sh - 1))
        cw = min(req.crop_w or sw, sw - cx)
        ch = min(req.crop_h or sh, sh - cy)
        if cw < 10 or ch < 10:
            # Crop is effectively outside the screen — drop it entirely
            req = req.model_copy(update={"crop_x": None, "crop_y": None,
                                         "crop_w": None, "crop_h": None})
        elif (cx, cy, cw, ch) != (req.crop_x, req.crop_y, req.crop_w, req.crop_h):
            req = req.model_copy(update={"crop_x": cx, "crop_y": cy,
                                         "crop_w": cw, "crop_h": ch})


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

    # Show orange border around the capture area (excluded from the recording)
    crop_arg = {"x": req.crop_x, "y": req.crop_y, "w": req.crop_w, "h": req.crop_h} \
               if any(v is not None for v in [req.crop_x, req.crop_y, req.crop_w, req.crop_h]) else None
    _start_recording_border(screen, crop_arg)

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

    _stop_recording_border()
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
        screens = _list_screens_mac()
        # POSIX: resume the stopped process
        try:
            _ffmpeg_proc.send_signal(signal.SIGCONT)
        except Exception as exc:
            return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})

    _recording_start = time.monotonic()
    _paused_at = None

    # Restore border on resume
    screen = screens[_last_start_req.screen_index] if _last_start_req.screen_index < len(screens) else screens[0]
    crop_arg = {"x": _last_start_req.crop_x, "y": _last_start_req.crop_y,
                "w": _last_start_req.crop_w, "h": _last_start_req.crop_h} \
               if any(v is not None for v in [_last_start_req.crop_x, _last_start_req.crop_y,
                                              _last_start_req.crop_w, _last_start_req.crop_h]) else None
    _start_recording_border(screen, crop_arg)

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
    _stop_recording_border()

    # Persist the raw recording path server-side so the Phase 3 narration widget
    # can fetch it via /api/recorder/latest-output without any path embedded in JS.
    if final:
        _write_latest_output({"raw": str(final), "final": str(final)})

    return {
        "ok": True, "status": "idle",
        "path": str(final) if final else None,
        "size_bytes": size,
        "elapsed": elapsed,
        "segments": len(_segments),
    }


def _write_latest_output(data: dict) -> None:
    """Write output paths to ~/.gator/latest_output.json for widget fetch."""
    try:
        p = Path.home() / ".gator" / "latest_output.json"
        p.parent.mkdir(exist_ok=True)
        existing = {}
        if p.exists():
            try:
                existing = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
        existing.update(data)
        p.write_text(json.dumps(existing), encoding="utf-8")
    except Exception:
        pass


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/api/recorder/status")
async def recorder_status():
    global _ffmpeg_proc
    ffmpeg = _FFMPEG or _find_ffmpeg()
    ffprobe = _FFPROBE or _find_ffprobe()
    log_path = str(_session_dir / "ffmpeg_log.txt") if _session_dir else None

    if _paused_at is not None:
        return {
            "status": "paused", "elapsed": _elapsed(), "size_bytes": 0,
            "path": str(_session_dir / f"{_session_tag}_final.mp4") if _session_dir else None,
            "ffmpeg": bool(ffmpeg), "ffmpeg_path": ffmpeg, "ffprobe_path": ffprobe,
            "segments": len(_segments), "log": log_path,
        }

    if _ffmpeg_proc is None or _ffmpeg_proc.poll() is not None:
        _ffmpeg_proc = None
        return {
            "status": "idle", "elapsed": 0, "size_bytes": 0, "path": None,
            "ffmpeg": bool(ffmpeg), "ffmpeg_path": ffmpeg, "ffprobe_path": ffprobe,
            "log": log_path,
        }

    size = _file_size(_recording_path) if _recording_path else 0
    return {
        "status": "recording", "elapsed": _elapsed(), "size_bytes": size,
        "path": str(_session_dir / f"{_session_tag}_final.mp4") if _session_dir else None,
        "pid": _ffmpeg_proc.pid,
        "ffmpeg": True, "ffmpeg_path": ffmpeg, "ffprobe_path": ffprobe,
        "segments": len(_segments), "log": log_path,
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


@router.get("/api/recorder/latest-output")
async def recorder_latest_output():
    """Return the latest recording/output paths so widgets don't embed paths in JS.

    Returns {raw, final, timestamp} — 'raw' is the raw recording, 'final' is the
    last merged output (TTS + music). Widgets fetch this on load instead of having
    the model bake a path string into a JS literal (which causes escaping bugs).
    """
    p = Path.home() / ".gator" / "latest_output.json"
    if not p.exists():
        return JSONResponse(status_code=404, content={"error": "no output yet"})
    try:
        return JSONResponse(json.loads(p.read_text(encoding="utf-8")))
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


class SetOutputRequest(BaseModel):
    final: str
    raw: str = ""


@router.post("/api/recorder/set-output")
async def recorder_set_output(req: SetOutputRequest):
    """Called by Phase 4 agent code after TTS/music merge to register the final path."""
    data: dict = {"final": req.final}
    if req.raw:
        data["raw"] = req.raw
    _write_latest_output(data)
    return {"ok": True}


class NarrationApprovedRequest(BaseModel):
    segments: list
    flags: dict = {}


@router.post("/api/recorder/narration-approved")
async def recorder_narration_approved(req: NarrationApprovedRequest):
    """Store approved narration segments server-side so the agent can read them.

    Called by the frontend postMessage intercept when the widget's Approve button
    fires. Writes to ~/.gator/narration_pending.json so the agent can read it via
    run_python without depending on browser sessionStorage (which is inaccessible
    to the agent).
    """
    gator_dir = Path.home() / ".gator"
    gator_dir.mkdir(exist_ok=True)
    pending = gator_dir / "narration_pending.json"
    pending.write_text(json.dumps({
        "segments": req.segments,
        "flags": req.flags,
        "timestamp": datetime.utcnow().isoformat(),
    }), encoding="utf-8")
    return {"ok": True, "path": str(pending)}


@router.get("/api/recorder/debug")
async def recorder_debug():
    """Returns current screen list and last ffmpeg log for diagnosing capture issues."""
    screens = await asyncio.to_thread(_list_screens_windows) if os.name == "nt" else await asyncio.to_thread(_list_screens_mac)
    log_lines = []
    if _session_dir:
        log_path = _session_dir / "ffmpeg_log.txt"
        try:
            log_lines = log_path.read_text(errors="replace").splitlines()[-80:]
        except OSError:
            pass
    return {"screens": screens, "log_tail": log_lines, "session_dir": str(_session_dir) if _session_dir else None}


@router.post("/api/recorder/tts-preview")
async def recorder_tts_preview(body: dict = Body(default={})):
    """Generate a short TTS audio preview via Lemonade and return it as audio/mpeg.
    Body: {text, voice, model, lemonade_url}
    """
    import httpx
    from fastapi.responses import Response as _Response
    text = (body.get("text") or "").strip()[:300]
    if not text:
        return JSONResponse(status_code=400, content={"error": "text required"})
    voice = body.get("voice") or "af_heart"
    model = body.get("model") or "kokoro-v1"
    lemonade_url = (body.get("lemonade_url") or "http://localhost:13305").rstrip("/")
    try:
        # Quick reachability check with short timeout — don't make the user
        # wait 15s if Lemonade is down. Any HTTP response (even 404) means
        # the server is alive.
        async with httpx.AsyncClient(timeout=3) as probe:
            try:
                await probe.get(lemonade_url + "/health")
            except httpx.ConnectError:
                return JSONResponse(status_code=502,
                                    content={"error": "Lemonade TTS is not running at " + lemonade_url})
            except httpx.HTTPError:
                pass  # server responded (even with error) — it's alive
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{lemonade_url}/v1/audio/speech",
                json={"model": model, "input": text, "voice": voice},
            )
        if r.status_code != 200:
            return JSONResponse(status_code=502,
                                content={"error": f"Lemonade {r.status_code}: {r.text[:200]}"})
        return _Response(content=r.content, media_type="audio/mpeg")
    except httpx.ConnectError:
        return JSONResponse(status_code=502, content={"error": "Lemonade TTS is not running"})
    except Exception as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})


@router.get("/api/recorder/serve-file")
async def recorder_serve_file(path: str):
    """Serve a local file (MP4/MP3) by absolute path for inline playback.
    Only serves files under the gator_demos output directory."""
    from fastapi.responses import FileResponse as _FileResponse
    p = Path(path).resolve()
    out = OUT_DIR.resolve()
    # Path traversal check: p must be inside out (a proper parent check,
    # not a string prefix match which `gator_demos_evil` would bypass)
    try:
        p.relative_to(out)
    except ValueError:
        return JSONResponse(status_code=403, content={"error": "path outside gator_demos"})
    if not p.exists():
        return JSONResponse(status_code=404, content={"error": "file not found"})
    suffix = p.suffix.lower()
    media = {"mp4": "video/mp4", "mp3": "audio/mpeg", "m4a": "audio/mp4"}.get(suffix[1:], "application/octet-stream")
    return _FileResponse(str(p), media_type=media)


@router.post("/api/recorder/open-widget")
async def recorder_open_widget():
    """Called by the REC badge click. Sets a flag the frontend polls to open
    the recorder widget HUD."""
    global _open_widget_request
    _open_widget_request = True
    return {"ok": True}


@router.get("/api/recorder/pending")
async def recorder_pending():
    """Frontend polls this every 2s. Returns and clears any pending notification."""
    global _pending_notification, _open_widget_request
    result = {"ok": True, "pending": False, "open_widget": _open_widget_request}
    if _open_widget_request:
        _open_widget_request = False
    if _pending_notification:
        msg = _pending_notification
        _pending_notification = None
        result["pending"] = True
        result["message"] = msg["message"]
        result["context_id"] = msg["context_id"]
    return result
