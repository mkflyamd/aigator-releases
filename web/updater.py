"""OTA update logic — manifest check, background download, installer launch."""

import asyncio
import hashlib
import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx
from log_sanitizer import sanitize
from packaging.version import Version

_log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

# The release workflow publishes SHA256SUMS.txt next to the installers; the
# newest published release is the update source.
CHECKSUMS_URL = "https://github.com/mkflyamd/aigator-releases/releases/latest/download/SHA256SUMS.txt"
RELEASE_PAGE_URL = "https://github.com/mkflyamd/aigator-releases/releases/latest"

# Pinned to the exact repo/path/asset this project publishes releases to.
_ALLOWED_INSTALLER_URL_RE = re.compile(
    r"^https://github\.com/mkflyamd/aigator-releases/releases/download/v([^/]+)/AI-Gator-\1-Windows-x64\.exe$"
)
_WINDOWS_ASSET_RE = re.compile(r"^AI-Gator-(\d+(?:\.\d+)*)-Windows-x64\.exe$")
_ANY_ASSET_RE = re.compile(r"^AI-Gator-(\d+(?:\.\d+)*)-[A-Za-z0-9_.-]+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# In-app install runs only for releases signed with the pinned cert. Set this to
# the first version the release workflow signs; until then the toast links to the
# release page instead of installing.
FIRST_SIGNED_VERSION: str | None = None

# Must match build/build.bat's SIGN_THUMBPRINT. If the signing cert is ever
# rotated, update both locations together.
EXPECTED_SIGNING_THUMBPRINT = "B09F5EF43A1D7BF0F97C4883D723BA1AF67A7F42"  # pragma: allowlist secret

VERSION_FILE = (
    Path(getattr(sys, "_MEIPASS")) / "version.txt"
    if getattr(sys, "frozen", False)
    else Path(__file__).parent.parent / "version.txt"
)


# ── State machine ─────────────────────────────────────────────────────────────


@dataclass
class UpdateInfo:
    version: str
    url: str
    sha256: str
    notes: str
    install_supported: bool = False


@dataclass
class _UpdateState:
    state: str = "idle"  # idle|checking|available|up_to_date|downloading|ready|error
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


def parse_checksums(text: str) -> tuple[str, str, str] | None:
    """Return (version, filename, sha256) of the Windows installer listed in a
    sha256sum-format file, or None if it has no valid entry."""
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts[0].lower(), parts[1].lstrip("*")
        name_match = _WINDOWS_ASSET_RE.match(name)
        if name_match and _SHA256_RE.match(digest):
            return name_match.group(1), name, digest
    return None


def parse_release_version(text: str) -> str | None:
    """Return the version of the first AI Gator asset listed in a sha256sum-format
    file, whatever its platform."""
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        match = _ANY_ASSET_RE.match(parts[1].lstrip("*"))
        if match:
            return match.group(1)
    return None


def _install_supported(version: str) -> bool:
    return (
        sys.platform == "win32"
        and FIRST_SIGNED_VERSION is not None
        and Version(version) >= Version(FIRST_SIGNED_VERSION)
    )


async def check_for_update() -> UpdateInfo | None:
    """Read the latest release's checksums and compare versions. Returns UpdateInfo
    if newer, else None. Failures are logged and leave the state idle. Only Windows
    gets an installer entry; other platforms are told a release exists and link to
    its page."""
    if not CHECKSUMS_URL:
        return None
    if _state.state in ("downloading", "ready"):
        return None
    _state.state = "checking"
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(CHECKSUMS_URL)
            resp.raise_for_status()
            text = resp.text
        if sys.platform == "win32":
            entry = parse_checksums(text)
            if entry is None:
                _log.warning("Update check: no Windows installer in the latest release checksums")
                _state.state = "idle"
                return None
            version, name, sha256 = entry
        else:
            version = parse_release_version(text)
            if version is None:
                _log.warning("Update check: no AI Gator assets in the latest release checksums")
                _state.state = "idle"
                return None
            name, sha256 = "", ""
        if Version(version) > Version(get_current_version()):
            url = f"https://github.com/mkflyamd/aigator-releases/releases/download/v{version}/{name}" if name else ""
            if url and not _ALLOWED_INSTALLER_URL_RE.match(url):
                _log.warning("Rejecting update v%s: untrusted source URL", version)
                _state.state = "idle"
                return None
            info = UpdateInfo(
                version=version,
                url=url,
                sha256=sha256,
                notes="",
                install_supported=_install_supported(version),
            )
            _state.info = info
            _state.state = "available"
            return info
        else:
            _state.state = "up_to_date"
            return None
    except Exception as exc:
        _log.warning("Update check failed: %s", sanitize(str(exc)))
        _state.state = "idle"
        return None


def _verify_authenticode_signature(path: Path) -> tuple[bool, str]:
    """Check the file's Authenticode signature via PowerShell. Returns (ok, reason)."""
    from proc_utils import no_window_kwargs

    try:
        result = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                f"$sig = Get-AuthenticodeSignature -LiteralPath '{path}'; "
                "Write-Output \"$($sig.Status)|$($sig.SignerCertificate.Thumbprint)\"",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            **no_window_kwargs(),
        )
    except Exception:
        return False, "invalid signature"

    if result.returncode != 0:
        return False, "invalid signature"

    parts = result.stdout.strip().split("|")
    if len(parts) != 2:
        return False, "invalid signature"
    status, thumbprint = parts
    # The signing cert is self-signed and not in the Trusted Root store on end-user
    # machines, so a correctly signed installer reports UnknownError (untrusted root),
    # not Valid. The pinned thumbprint below is the real trust anchor; tampered files
    # report HashMismatch and are still rejected.
    if status not in ("Valid", "UnknownError"):
        return False, "invalid signature"
    if thumbprint.strip().upper() != EXPECTED_SIGNING_THUMBPRINT:
        return False, "untrusted signer"
    return True, ""


async def download_update() -> None:
    """Stream installer to %TEMP%\\AIGatorInstaller.exe. Updates _state.progress."""
    if not _state.info:
        return
    if not _state.info.install_supported:
        _state.state = "error"
        _state.error = "In-app install is not available for this release"
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
        digest = hashlib.sha256(tmp_path.read_bytes()).hexdigest()
        if digest != _state.info.sha256:
            _log.warning(
                "OTA checksum mismatch for %s: expected %s, got %s",
                _state.info.url, _state.info.sha256, digest,
            )
            tmp_path.unlink(missing_ok=True)
            _state.state = "error"
            _state.error = "checksum mismatch"
            return

        sig_ok, sig_reason = _verify_authenticode_signature(tmp_path)
        if not sig_ok:
            _log.warning("OTA signature check failed for %s: %s", _state.info.url, sig_reason)
            tmp_path.unlink(missing_ok=True)
            _state.state = "error"
            _state.error = sig_reason
            return

        _state._installer_path = str(tmp_path)
        _state.state = "ready"
    except asyncio.CancelledError:
        _state.state = "idle"
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        _state.state = "error"
        _state.error = sanitize(str(exc))
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


_APP_EXE_NAME = "AI Gator.exe"

# Paths reach PowerShell through the environment, so no quoting rules apply to them.
_INSTALL_SCRIPT = (
    "Start-Sleep -Seconds 1; "
    "$dir = $env:AIGATOR_APP_DIR.TrimEnd('\\') + '\\'; "
    "Get-Process | Where-Object { $_.Id -ne $PID -and $_.Path -and "
    "$_.Path.StartsWith($dir, [StringComparison]::OrdinalIgnoreCase) } | "
    "Stop-Process -Force -ErrorAction SilentlyContinue; "
    "Start-Sleep -Seconds 2; "
    "try { "
    "$p = Start-Process -FilePath $env:AIGATOR_INSTALLER -ArgumentList '/S','--updated','--force-run' "
    "-Wait -PassThru -ErrorAction Stop; "
    "$ok = ($p.ExitCode -eq 0); $why = 'installer exit code ' + $p.ExitCode "
    "} catch { $ok = $false; $why = $_.Exception.Message }; "
    "if (-not $ok) { "
    "Add-Content -LiteralPath $env:AIGATOR_UPDATE_LOG -Value ((Get-Date -Format o) + ' update failed: ' + $why); "
    "Start-Process -FilePath ($dir + $env:AIGATOR_APP_EXE) "
    "}"
)


def launch_installer() -> None:
    """Hand the verified installer to a detached helper that closes the app,
    installs silently and relaunches. If the installer fails, the helper logs the
    failure and relaunches the installed app. This process is stopped by the helper."""
    path = _state._installer_path
    if not path or not Path(path).exists():
        _log.warning("Install requested but the installer file is missing")
        _state.state = "error"
        _state.error = "Installer file not found"
        return
    if not getattr(sys, "frozen", False):
        _log.warning("Install requested outside the packaged app")
        _state.state = "error"
        _state.error = "Install is only available in the packaged app"
        return
    # <app>/resources/backend/aigator-backend.exe -> <app>
    app_dir = str(Path(sys.executable).resolve().parents[2])
    from proc_utils import no_window_kwargs

    kwargs = no_window_kwargs()
    kwargs["creationflags"] = (
        kwargs.get("creationflags", 0)
        | subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.CREATE_BREAKAWAY_FROM_JOB
    )
    kwargs["env"] = {
        **os.environ,
        "AIGATOR_INSTALLER": path,
        "AIGATOR_APP_DIR": app_dir,
        "AIGATOR_APP_EXE": _APP_EXE_NAME,
        "AIGATOR_UPDATE_LOG": str(Path(path).with_suffix(".log")),
    }
    _log.info("Launching update installer %s", path)
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _INSTALL_SCRIPT],
        **kwargs,
    )


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
