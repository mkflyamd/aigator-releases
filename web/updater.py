"""OTA update logic — manifest check, background download, installer launch."""
import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx
from packaging.version import Version

# ── Configuration ─────────────────────────────────────────────────────────────

MANIFEST_URL = "https://mkflyamd.github.io/aigator-releases/latest.json"

VERSION_FILE = Path(__file__).parent.parent / "version.txt"


# ── State machine ─────────────────────────────────────────────────────────────

@dataclass
class UpdateInfo:
    version: str
    url: str
    notes: str


@dataclass
class _UpdateState:
    state: str = "idle"   # idle|checking|available|up_to_date|downloading|ready|error
    info: UpdateInfo | None = None
    progress: int = 0
    error: str | None = None
    _installer_path: str | None = None


_state = _UpdateState()


# ── Core functions ────────────────────────────────────────────────────────────

def get_current_version() -> str:
    """Read version from version.txt; fall back to 0.0.0 if missing."""
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "0.0.0"


async def check_for_update() -> UpdateInfo | None:
    """Fetch manifest and compare versions. Returns UpdateInfo if newer, else None.
    Network failures are silent — no state change, returns None."""
    if not MANIFEST_URL:
        return None
    if _state.state in ("downloading", "ready"):
        return None
    _state.state = "checking"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(MANIFEST_URL)
            resp.raise_for_status()
            data = resp.json()
        if Version(data["version"]) > Version(get_current_version()):
            info = UpdateInfo(
                version=data["version"],
                url=data["url"],
                notes=data.get("notes", ""),
            )
            _state.info = info
            _state.state = "available"
            return info
        else:
            _state.state = "up_to_date"
            return None
    except Exception:
        _state.state = "idle"
        return None


async def download_update() -> None:
    """Stream installer to %TEMP%\\AIGatorInstaller.exe. Updates _state.progress."""
    if not _state.info:
        return
    if not _state.info.url.startswith("https://"):
        _state.state = "error"
        _state.error = "Installer URL must use HTTPS"
        return
    _state.state = "downloading"
    _state.progress = 0
    _state.error = None
    tmp_path = Path(tempfile.gettempdir()) / "AIGatorInstaller.exe"
    try:
        async with httpx.AsyncClient(timeout=600, follow_redirects=True) as client:
            async with client.stream("GET", _state.info.url) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                with open(tmp_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            _state.progress = int(downloaded / total * 100)
        _state._installer_path = str(tmp_path)
        _state.state = "ready"
    except asyncio.CancelledError:
        _state.state = "idle"
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        _state.state = "error"
        _state.error = str(exc)
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def launch_installer() -> None:
    """Launch installer silently, then signal watchdog to quit."""
    import subprocess
    path = _state._installer_path
    if not path or not Path(path).exists():
        _state.state = "error"
        _state.error = "Installer file not found"
        return
    subprocess.Popen([path, "/SILENT"])
    # Signal watchdog to quit cleanly; installer kills remaining processes
    try:
        httpx.post("http://localhost:8001/quit", timeout=2)
    except Exception:
        pass


async def run_update_check_loop(cfg: dict) -> None:
    """Background loop: check on startup, then every N days (from cfg)."""
    interval_days = cfg.get("update_check_interval_days", 1)
    interval_seconds = max(1, int(interval_days)) * 86400
    try:
        await check_for_update()
        while True:
            await asyncio.sleep(interval_seconds)
            await check_for_update()
    except asyncio.CancelledError:
        pass
