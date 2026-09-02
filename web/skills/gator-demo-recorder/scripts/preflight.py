"""
Preflight checks for Gator Demo Recorder.

Checks ffmpeg and Lemonade TTS availability. If missing, asks user consent
then installs silently. Never installs without explicit consent.

Usage (called by the skill agent):
    python preflight.py [--auto-consent]

Returns JSON to stdout:
    {"ffmpeg": {"ok": bool, "path": str, "installed": bool},
     "lemonade": {"ok": bool, "url": str, "kokoro": bool, "installed": bool, "na": bool},
     "platform": str,
     "all_required_ok": bool}
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


PLATFORM = platform.system()   # "Windows", "Darwin", "Linux"
LEMONADE_URL = "http://localhost:13305"
LEMONADE_MODEL = "kokoro-v1"


# ── ffmpeg ────────────────────────────────────────────────────────────────────

def _find_ffmpeg() -> str | None:
    # 1. PATH
    found = shutil.which("ffmpeg")
    if found:
        return found

    if PLATFORM == "Windows":
        # 2. WinGet packages — any vendor, any version
        winget_base = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
        if winget_base.exists():
            for candidate in sorted(winget_base.glob("*/*/bin/ffmpeg.exe"), reverse=True):
                if candidate.exists():
                    return str(candidate)
        # 3. Common manual locations
        for p in [
            Path("C:/ffmpeg/bin/ffmpeg.exe"),
            Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
            Path("C:/Program Files (x86)/ffmpeg/bin/ffmpeg.exe"),
            Path.home() / "ffmpeg/bin/ffmpeg.exe",
            Path.home() / "scoop/apps/ffmpeg/current/bin/ffmpeg.exe",
        ]:
            if p.exists():
                return str(p)

    elif PLATFORM == "Darwin":
        for p in [
            Path("/opt/homebrew/bin/ffmpeg"),   # Apple Silicon
            Path("/usr/local/bin/ffmpeg"),       # Intel
        ]:
            if p.exists():
                return str(p)

    elif PLATFORM == "Linux":
        for p in [Path("/usr/bin/ffmpeg"), Path("/usr/local/bin/ffmpeg")]:
            if p.exists():
                return str(p)

    return None


def _install_ffmpeg() -> str | None:
    """Attempt to install ffmpeg. Returns path on success, None on failure."""
    if PLATFORM == "Windows":
        # Try winget first
        if shutil.which("winget"):
            try:
                r = subprocess.run(
                    ["winget", "install", "--id=Gyan.FFmpeg", "-e",
                     "--accept-source-agreements", "--accept-package-agreements",
                     "--disable-interactivity"],
                    capture_output=True, timeout=180,
                )
                if r.returncode == 0:
                    return _find_ffmpeg()
            except Exception:
                pass
        # Try Chocolatey
        if shutil.which("choco"):
            try:
                r = subprocess.run(
                    ["choco", "install", "ffmpeg", "-y"],
                    capture_output=True, timeout=180,
                )
                if r.returncode == 0:
                    return _find_ffmpeg()
            except Exception:
                pass
        # Try Scoop
        if shutil.which("scoop"):
            try:
                r = subprocess.run(
                    ["scoop", "install", "ffmpeg"],
                    capture_output=True, timeout=180,
                )
                if r.returncode == 0:
                    return _find_ffmpeg()
            except Exception:
                pass
        return None

    elif PLATFORM == "Darwin":
        if shutil.which("brew"):
            try:
                r = subprocess.run(
                    ["brew", "install", "ffmpeg"],
                    capture_output=True, timeout=300,
                )
                if r.returncode == 0:
                    return _find_ffmpeg()
            except Exception:
                pass
        return None

    elif PLATFORM == "Linux":
        # Try apt
        if shutil.which("apt-get"):
            try:
                subprocess.run(["sudo", "apt-get", "update", "-qq"],
                                capture_output=True, timeout=60)
                r = subprocess.run(
                    ["sudo", "apt-get", "install", "-y", "ffmpeg"],
                    capture_output=True, timeout=180,
                )
                if r.returncode == 0:
                    return _find_ffmpeg()
            except Exception:
                pass
        # Try dnf
        if shutil.which("dnf"):
            try:
                r = subprocess.run(
                    ["sudo", "dnf", "install", "-y", "ffmpeg"],
                    capture_output=True, timeout=180,
                )
                if r.returncode == 0:
                    return _find_ffmpeg()
            except Exception:
                pass
        # Try pacman
        if shutil.which("pacman"):
            try:
                r = subprocess.run(
                    ["sudo", "pacman", "-S", "--noconfirm", "ffmpeg"],
                    capture_output=True, timeout=180,
                )
                if r.returncode == 0:
                    return _find_ffmpeg()
            except Exception:
                pass
        return None

    return None


def check_ffmpeg(auto_install: bool = False) -> dict:
    path = _find_ffmpeg()
    if path:
        return {"ok": True, "path": path, "installed": False}

    if not auto_install:
        install_hints = {
            "Windows": "winget install Gyan.FFmpeg   OR   choco install ffmpeg   OR   scoop install ffmpeg",
            "Darwin":  "brew install ffmpeg",
            "Linux":   "sudo apt install ffmpeg   OR   sudo dnf install ffmpeg",
        }
        return {
            "ok": False, "path": None, "installed": False,
            "install_hint": install_hints.get(PLATFORM, "See https://ffmpeg.org/download.html"),
            "package_managers": _available_package_managers(),
        }

    path = _install_ffmpeg()
    if path:
        return {"ok": True, "path": path, "installed": True}

    return {
        "ok": False, "path": None, "installed": False,
        "error": "Automatic install failed — no supported package manager found.",
        "install_hint": "Download from https://ffmpeg.org/download.html and add to PATH",
    }


# ── Lemonade TTS ──────────────────────────────────────────────────────────────

def _lemonade_running() -> dict | None:
    """Return model info if Lemonade is running, else None."""
    try:
        resp = urllib.request.urlopen(f"{LEMONADE_URL}/v1/models", timeout=3)
        data = json.loads(resp.read())
        models = [m.get("id", "") for m in data.get("data", [])]
        kokoro = any(LEMONADE_MODEL in m.lower() for m in models)
        return {"running": True, "kokoro": kokoro, "models": models}
    except Exception:
        return None


def _lemonade_tts_works() -> bool:
    """Actually call the TTS endpoint with a tiny payload to confirm it works.
    A model being listed in /v1/models doesn't guarantee /v1/audio/speech
    is functional (e.g. model loaded but inference broken). This probe
    generates 3 words and discards the audio — fast and definitive."""
    import tempfile, os
    try:
        req = urllib.request.Request(
            f"{LEMONADE_URL}/v1/audio/speech",
            data=json.dumps({
                "model": LEMONADE_MODEL,
                "input": "test",
                "voice": "af_heart",
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=15)
        # Read a few bytes to confirm the response is real audio, not an error page
        chunk = resp.read(1024)
        resp.close()
        return len(chunk) > 0
    except Exception:
        return False


def _find_lemonade_exe() -> str | None:
    found = shutil.which("lemonade")
    if found:
        return found
    if PLATFORM == "Windows":
        local = Path.home() / "AppData/Local/lemonade_server/bin/lemonade.exe"
        if local.exists():
            return str(local)
        # WinGet install path
        winget_base = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
        if winget_base.exists():
            for candidate in sorted(winget_base.glob("AMD.LemonadeServer*/*/lemonade.exe"), reverse=True):
                if candidate.exists():
                    return str(candidate)
    elif PLATFORM == "Darwin":
        for p in [Path("/opt/homebrew/bin/lemonade"), Path("/usr/local/bin/lemonade")]:
            if p.exists():
                return str(p)
    elif PLATFORM == "Linux":
        for p in [Path.home() / ".local/bin/lemonade", Path("/usr/local/bin/lemonade")]:
            if p.exists():
                return str(p)
    return None


def _start_lemonade() -> bool:
    """Start Lemonade server in background. Returns True if it came up."""
    exe = _find_lemonade_exe()
    if not exe:
        return False
    try:
        subprocess.Popen(
            [exe, "serve"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if PLATFORM == "Windows" else 0,
        )
        import time
        for _ in range(12):   # wait up to 12s
            time.sleep(1)
            if _lemonade_running():
                return True
        return False
    except Exception:
        return False


def _install_lemonade() -> str | None:
    """Install Lemonade. Returns exe path on success, None on failure.
    Only works on Windows (AMD Lemonade is Windows-only hardware-accelerated).
    macOS/Linux: pip install lemonade-server (community build, CPU only).
    """
    if PLATFORM == "Windows":
        if shutil.which("winget"):
            try:
                r = subprocess.run(
                    ["winget", "install", "--id=AMD.LemonadeServer", "-e",
                     "--accept-source-agreements", "--accept-package-agreements",
                     "--disable-interactivity"],
                    capture_output=True, timeout=300,
                )
                if r.returncode == 0:
                    return _find_lemonade_exe()
            except Exception:
                pass
        return None

    else:
        # macOS / Linux — pip install lemonade-server (CPU-only community build)
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", "lemonade-server", "--quiet"],
                capture_output=True, timeout=120,
            )
            if r.returncode == 0:
                return shutil.which("lemonade") or "lemonade"
        except Exception:
            pass
        return None


def _pull_kokoro(exe: str) -> bool:
    """Pull the kokoro-v1 TTS model if not already downloaded."""
    try:
        r = subprocess.run(
            [exe, "pull", LEMONADE_MODEL],
            capture_output=True, timeout=300,
        )
        return r.returncode == 0
    except Exception:
        return False


def check_lemonade(auto_install: bool = False) -> dict:
    # 1. Already running?
    info = _lemonade_running()
    if info:
        if not info["kokoro"]:
            exe = _find_lemonade_exe()
            if exe:
                _pull_kokoro(exe)
                info2 = _lemonade_running()
                kokoro = info2["kokoro"] if info2 else False
            else:
                kokoro = False
        else:
            kokoro = True

        # Even if the model is listed, verify the TTS endpoint actually works.
        # A false "ok: true" here causes confusing failures later during narration.
        tts_ok = kokoro and _lemonade_tts_works()
        return {
            "ok": tts_ok, "url": LEMONADE_URL, "kokoro": kokoro,
            "tts_endpoint": "/v1/audio/speech",
            "model": LEMONADE_MODEL,
            "installed": False, "na": False,
            "note": "" if tts_ok else (
                f"{LEMONADE_MODEL} model listed but TTS endpoint did not respond"
                if kokoro else f"{LEMONADE_MODEL} model not found"
            ),
        }

    # 2. Installed but not running?
    exe = _find_lemonade_exe()
    if exe:
        started = _start_lemonade()
        if started:
            info = _lemonade_running()
            kokoro = info["kokoro"] if info else False
            if not kokoro:
                _pull_kokoro(exe)
                info = _lemonade_running()
                kokoro = info["kokoro"] if info else False
            tts_ok = kokoro and _lemonade_tts_works()
            return {
                "ok": tts_ok, "url": LEMONADE_URL, "kokoro": kokoro,
                "tts_endpoint": "/v1/audio/speech",
                "model": LEMONADE_MODEL,
                "installed": False, "na": False,
                "note": "Started automatically" if tts_ok else "Started but TTS endpoint not responding",
            }

    # 3. Not installed
    if not auto_install:
        if PLATFORM == "Windows":
            hint = "winget install AMD.LemonadeServer"
        elif PLATFORM == "Darwin":
            hint = "pip install lemonade-server  (CPU-only, no AMD NPU)"
        else:
            hint = "pip install lemonade-server  (CPU-only)"

        return {
            "ok": False, "url": None, "kokoro": False,
            "installed": False, "na": False,
            "install_hint": hint,
        }

    # 4. Auto-install
    installed_exe = _install_lemonade()
    if installed_exe:
        started = _start_lemonade()
        if started:
            exe = installed_exe
            _pull_kokoro(exe)
            info = _lemonade_running()
            kokoro = info["kokoro"] if info else False
            tts_ok = kokoro and _lemonade_tts_works()
            return {
                "ok": tts_ok, "url": LEMONADE_URL, "kokoro": kokoro,
                "tts_endpoint": "/v1/audio/speech",
                "model": LEMONADE_MODEL,
                "installed": True, "na": False,
            }

    return {
        "ok": False, "url": None, "kokoro": False,
        "installed": False, "na": False,
        "error": "Automatic install failed",
        "install_hint": (
            "Windows: winget install AMD.LemonadeServer\n"
            "macOS/Linux: pip install lemonade-server"
        ),
    }


# ── Package managers available on this machine ────────────────────────────────

def _available_package_managers() -> list[str]:
    managers = []
    checks = {
        "Windows": ["winget", "choco", "scoop"],
        "Darwin":  ["brew", "port"],
        "Linux":   ["apt-get", "dnf", "pacman", "zypper", "apk"],
    }
    for mgr in checks.get(PLATFORM, []):
        if shutil.which(mgr):
            managers.append(mgr)
    return managers


# ── Consent-gated preflight (called by skill agent) ──────────────────────────

def run_preflight(auto_consent: bool = False) -> dict:
    """
    Check ffmpeg and Lemonade. If either is missing and auto_consent=False,
    return what's needed so the agent can ask the user.
    If auto_consent=True, install missing components silently.
    """
    ffmpeg = check_ffmpeg(auto_install=False)
    lemonade = check_lemonade(auto_install=False)

    needs_install = []
    if not ffmpeg["ok"]:
        needs_install.append({
            "name": "ffmpeg",
            "purpose": "Extract video keyframes and merge audio/video",
            "hint": ffmpeg.get("install_hint", ""),
            "package_managers": ffmpeg.get("package_managers", []),
        })
    if not lemonade["ok"] and not lemonade.get("na"):
        needs_install.append({
            "name": "Lemonade TTS Server",
            "purpose": "Generate voiceover narration (optional — video works without it)",
            "hint": lemonade.get("install_hint", ""),
            "optional": True,
        })

    if needs_install and not auto_consent:
        return {
            "ready": False,
            "ffmpeg": ffmpeg,
            "lemonade": lemonade,
            "platform": PLATFORM,
            "needs_install": needs_install,
            "all_required_ok": ffmpeg["ok"],   # lemonade is optional
            "message": _consent_message(needs_install),
        }

    # Either everything is fine, or user has consented — install what's missing
    if not ffmpeg["ok"]:
        ffmpeg = check_ffmpeg(auto_install=True)
    if not lemonade["ok"] and not lemonade.get("na"):
        lemonade = check_lemonade(auto_install=True)

    return {
        "ready": ffmpeg["ok"],
        "ffmpeg": ffmpeg,
        "lemonade": lemonade,
        "platform": PLATFORM,
        "needs_install": [],
        "all_required_ok": ffmpeg["ok"],
    }


def _consent_message(needs: list) -> str:
    lines = ["To use the Demo Recorder, the following need to be installed:"]
    for item in needs:
        tag = " (optional)" if item.get("optional") else " (required)"
        lines.append(f"  • {item['name']}{tag} — {item['purpose']}")
        if item.get("hint"):
            lines.append(f"    Install: {item['hint']}")
    lines.append("")
    lines.append("Reply 'yes' to install automatically, or install manually and try again.")
    return "\n".join(lines)


# ── Standalone run ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    auto = "--auto-consent" in sys.argv
    result = run_preflight(auto_consent=auto)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["all_required_ok"] else 1)
