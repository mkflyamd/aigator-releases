"""Cross-platform subprocess helpers.

The server runs windowless (the tray launches it with CREATE_NO_WINDOW). On
Windows, a windowless parent that spawns a console child causes the OS to
allocate a new visible console window per spawn — the "flashing windows"
testers see on every tool/MCP call. Passing CREATE_NO_WINDOW on the child
suppresses that. No-op on non-Windows platforms.
"""

import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

_log = logging.getLogger(__name__)


def no_window_kwargs() -> dict:
    """Popen/run kwargs that suppress a console window on Windows."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def group_kwargs() -> dict:
    """Popen kwargs that start the child in its own process group (Windows) or session (POSIX), with no console window."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _k32.AssignProcessToJobObject.restype = wintypes.BOOL
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.TerminateJobObject.restype = wintypes.BOOL
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.CloseHandle.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]


def attach_job(proc: subprocess.Popen) -> None:
    """Put a freshly started child in a Windows Job Object so its tree can be killed after the parent exits.

    taskkill /T follows parent-pid links, which are gone once the shell exits and leaves a child behind.
    The job is only terminated on request (no kill-on-close): a command that exits normally leaves its
    daemons running. No-op on POSIX, where killpg covers the process group.
    """
    if sys.platform != "win32":
        return
    job = _k32.CreateJobObjectW(None, None)
    if not job:
        return
    if not _k32.AssignProcessToJobObject(job, int(proc._handle)):
        _k32.CloseHandle(job)
        return
    proc._gator_job = job


def release_job(proc: subprocess.Popen) -> None:
    """Drop the job handle once the run is over; processes in the job keep running."""
    job = getattr(proc, "_gator_job", None)
    if job:
        proc._gator_job = None
        _k32.CloseHandle(job)


def kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill a child started with group_kwargs() and everything it spawned."""
    if sys.platform == "win32":
        job = getattr(proc, "_gator_job", None)
        if job:
            proc._gator_job = None
            _k32.TerminateJobObject(job, 1)
            _k32.CloseHandle(job)
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True, check=False, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


# ── Output-file reporter ─────────────────────────────────────────────────────
# Shell/Python builds (e.g. the marketplace pptx skill driving pptxgenjs through
# run_shell) write documents to disk inside opaque command strings — the tool
# layer never "sees" the file being born, so the final path is left to the
# model's memory, which drifts (decks silently landing in ~/Downloads, or the
# agent forgetting it produced anything). These helpers snapshot the likely
# output dirs before a command runs and diff afterwards, so newly created or
# overwritten document/image files are surfaced as real absolute paths in the
# tool RESULT — reported from the plumbing, not reconstructed by the model.

# Document + image outputs worth reporting. Kept tight so installs/renders of
# incidental files don't spam the result.
_REPORTABLE_EXTS = {
    ".pptx", ".docx", ".xlsx", ".pdf", ".csv",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
}

_MIME_TYPES = {
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

# Directories never worth walking — huge and never the intended deliverable.
_SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__", ".cache", "site-packages"}

# Safety cap so a snapshot of a large tree (e.g. cwd = repo root) stays cheap.
_MAX_FILES_SCANNED = 5000


def _iter_output_files(root: Path):
    """Yield reportable files under `root`, skipping heavy dirs, capped for speed."""
    seen = 0
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() in _REPORTABLE_EXTS:
                    yield Path(dirpath) / fn
                seen += 1
                if seen >= _MAX_FILES_SCANNED:
                    return
    except OSError:
        return


def watched_output_dirs(cwd: str = "") -> list[Path]:
    """The dirs a build is likely to write into: the command's cwd, ~/Downloads,
    and ~/.gator/outputs. De-duplicated; only existing dirs are returned."""
    home = Path.home()
    candidates = []
    if cwd:
        candidates.append(Path(cwd))
    candidates.append(home / "Downloads")
    candidates.append(home / ".gator" / "outputs")
    out, seen = [], set()
    for c in candidates:
        try:
            rc = c.resolve()
        except OSError:
            continue
        key = os.path.normcase(str(rc))
        if key in seen:
            continue
        seen.add(key)
        if rc.is_dir():
            out.append(rc)
    return out


def snapshot_outputs(dirs) -> dict:
    """Return {absolute_path: mtime_ns} for reportable files under each dir."""
    snap = {}
    for d in dirs:
        for f in _iter_output_files(Path(d)):
            try:
                snap[os.path.normcase(str(f))] = (str(f), f.stat().st_mtime_ns)
            except OSError:
                continue
    return snap


def diff_outputs(before: dict, dirs) -> list[dict]:
    """Files created or modified since `before` was taken. Returns a list of
    {path, size_bytes, mime_type}, newest first."""
    import mimetypes
    after = snapshot_outputs(dirs)
    changed = []
    for key, (path, mtime) in after.items():
        prev = before.get(key)
        if prev is not None and prev[1] == mtime:
            continue  # unchanged
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        mime, _ = mimetypes.guess_type(path)
        changed.append({
            "path": path,
            "size_bytes": size,
            "mime_type": _MIME_TYPES.get(Path(path).suffix.lower(), mime) or "application/octet-stream",
            "_mtime": mtime,
        })
    changed.sort(key=lambda c: c["_mtime"], reverse=True)
    for c in changed:
        del c["_mtime"]
    return changed


_node_path_done = False


def ensure_bundled_node_on_path() -> str | None:
    """Put AI Gator's bundled Node at the front of PATH, if present.

    Every distribution drops a portable Node into the app folder (next to the
    `web/` dir): `<app>/node` on the run-from-source one-liners, `<app>/node`
    one level higher on the exe install. We prepend its bin dir to PATH so
    npx/node MCP servers resolve to our copy first — immune to a missing system
    Node, a stale version, or a GUI app not inheriting the shell PATH.

    Idempotent. Returns the bin dir added (or already present), else None.
    """
    global _node_path_done
    web_dir = Path(__file__).resolve().parent
    # Candidate <app>/node dirs for the two install layouts.
    candidates = [web_dir.parent / "node", web_dir.parent.parent / "node"]
    is_win = sys.platform == "win32"
    for cand in candidates:
        node_exe = cand / ("node.exe" if is_win else "bin/node")
        if not node_exe.exists():
            continue
        bin_dir = str(node_exe.parent)
        parts = os.environ.get("PATH", "").split(os.pathsep)
        if parts and os.path.normcase(parts[0]) == os.path.normcase(bin_dir):
            _node_path_done = True
            return bin_dir  # already at front
        os.environ["PATH"] = os.pathsep.join([bin_dir, *parts])
        _node_path_done = True
        _log.info("Bundled Node added to PATH: %s", bin_dir)
        return bin_dir
    return None
