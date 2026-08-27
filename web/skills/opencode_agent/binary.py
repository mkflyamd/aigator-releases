"""Bundled OpenCode binary resolution + self-heal.

Extracted from the now-removed instance_manager.py (which owned the full
`opencode serve` lifecycle — reaper, port allocation, persistence — that the
deprecated serve+attach path needed). The bare path (generic_agent.py's
OPENCODE_BARE_AGENT) only needs to locate and verify the bundled binary, so
that's all that lives here now.
"""
from __future__ import annotations

import logging
import os
import secrets
import shutil
import subprocess
import sys
import threading
from pathlib import Path

_log = logging.getLogger(__name__)

# Guards the self-heal copy so concurrent spawns/attaches (or two Gator
# instances sharing one node/ dir) never race the materialize. Only taken on
# the slow path (binary missing) — the hot path is a lock-free existence check.
_heal_lock = threading.Lock()
# One-time "opencode --version actually runs" preflight per process. Cleared
# whenever self-heal materializes a binary so a mid-session heal re-verifies.
_preflight_ok = False


def _supports_avx2() -> bool:
    """Mirror opencode postinstall.mjs's AVX2 detection (Windows path).

    The opencode binary ships in two x64 flavors: a plain build that REQUIRES
    AVX2 and a `-baseline` build that does not. Running the AVX2 build on a CPU
    without AVX2 crashes with an illegal-instruction fault. Postinstall picks
    the variant via this probe; we must replicate it so self-heal never
    materializes a SIGILL-ing binary. Default False (→ baseline) on any doubt.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        # IsProcessorFeaturePresent(PF_AVX2_INSTRUCTIONS_AVAILABLE = 40)
        return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(40))
    except Exception:
        return False


def _opencode_platform_packages() -> list[str]:
    """Ordered list of acceptable platform packages for this CPU, safest first.

    Non-AVX2 x64 (or uncertain): baseline ONLY — never the AVX2 build (SIGILL).
    AVX2 x64: prefer the AVX2 build, fall back to baseline (safe, just slower).
    arm64: the single arm64 package. Mirrors postinstall.mjs packageNames(),
    minus the unsafe non-AVX2→AVX2 fallback (we error instead of crashing).
    """
    arch = "arm64" if "arm" in (os.environ.get("PROCESSOR_ARCHITECTURE", "").lower()) else "x64"
    if arch == "arm64":
        return ["opencode-windows-arm64"]
    if _supports_avx2():
        return ["opencode-windows-x64", "opencode-windows-x64-baseline"]
    return ["opencode-windows-x64-baseline"]  # never fall back to the AVX2 build


def _ensure_opencode_binary(node_dir: Path) -> None:
    """Ensure `bin/opencode.exe` (the file the opencode.cmd shim executes) exists.

    Root-cause fix for the recurring "OpenCode won't start" outage: opencode's
    own postinstall is destructive-on-retry (unlinks the binary before re-copy,
    only succeeds if a verify step passes) and WakeGator could re-trigger it and
    leave `bin/opencode.exe` deleted-and-not-replaced. The signed platform
    binary survives under node_modules/opencode-ai/node_modules/<pkg>/bin, so we
    re-materialize the CORRECT variant from there. Windows-only (the .cmd shim
    layout); a no-op elsewhere.
    """
    global _preflight_ok
    if sys.platform != "win32":
        return
    oc_ai = node_dir / "node_modules" / "opencode-ai"
    target = oc_ai / "bin" / "opencode.exe"
    # Hot path — lock-free, no subprocess, no AVX2 probe when already present.
    if target.exists():
        return
    with _heal_lock:
        if target.exists():  # another thread/instance healed while we waited
            return
        source = None
        for pkg in _opencode_platform_packages():
            cand = oc_ai / "node_modules" / pkg / "bin" / "opencode.exe"
            if cand.exists():
                source = cand
                break
        if source is None:
            raise RuntimeError(
                "OpenCode binary is missing and could not be repaired "
                "(no matching platform package found) — re-run WakeGator."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.parent / f".opencode.exe.heal-{os.getpid()}-{secrets.token_hex(4)}"
        try:
            shutil.copyfile(source, tmp)
            os.replace(tmp, target)  # atomic on same volume
        except (PermissionError, OSError) as exc:
            # A peer instance may be executing target (Windows locks running
            # exes). If it now exists, the peer healed it — treat as success.
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            if target.exists():
                pass
            else:
                raise RuntimeError(
                    f"OpenCode binary is missing and could not be repaired ({exc}) — re-run WakeGator."
                )
        _preflight_ok = False  # force re-verify after a heal (atomic under lock)
        _log.warning(
            "[opencode-selfheal] Re-materialized missing bin/opencode.exe from %s. "
            "If this recurs, an install step (WakeGator re-run / postinstall) is deleting it.",
            source.parent.parent.name,
        )


def _opencode_preflight(opencode_cmd: Path) -> None:
    """Run `opencode --version` once per process; raise a clear error on failure
    instead of letting a spawn hit a silent 30s readiness timeout. Cheap after
    the first success (cached flag). MUST be called from a worker thread, never
    the event loop — it spawns a subprocess."""
    global _preflight_ok
    if _preflight_ok:
        return
    try:
        r = subprocess.run(
            build_opencode_command(opencode_cmd, ["--version"]),
            capture_output=True, text=True, timeout=30, **_no_window_kwargs(),
        )
    except Exception as exc:
        raise RuntimeError(f"OpenCode binary failed to run (--version errored: {exc}) — re-run WakeGator.")
    if r.returncode != 0:
        raise RuntimeError(
            f"OpenCode binary failed to run (--version exit {r.returncode}: "
            f"{(r.stderr or r.stdout or '').strip()[:200]}) — re-run WakeGator."
        )
    _preflight_ok = True


def _no_window_kwargs() -> dict:
    """CREATE_NO_WINDOW on Windows so preflight/subprocess calls don't flash a
    console; empty elsewhere."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def find_bundled_opencode() -> Path | None:
    """Locate the opencode binary installed into the bundled portable Node.

    npm's global-install layout differs by platform for `--prefix DIR`:
    Windows links executables directly into DIR (as .cmd shims); Unix links
    them into DIR/bin (confirmed against npm's own docs, not assumed - this
    is also exactly why WakeGator.sh already expects node itself at
    node/bin/node, not node/node, unlike the flat node/node.exe layout on
    Windows). NOT empirically tested on macOS/Linux - no Mac/Linux machine
    was available to verify this against a real install; it's built from
    npm's documented behavior and by direct analogy with the already-working
    Node path convention in WakeGator.sh, not verified execution.

    Before returning, self-heals a missing `bin/opencode.exe` (the file the
    Windows .cmd shim executes) — see _ensure_opencode_binary. The return
    contract is unchanged (still the .cmd shim path on Windows), so callers and
    build_opencode_command are untouched.
    """
    web_dir = Path(__file__).resolve().parent.parent.parent
    candidates = [web_dir.parent / "node", web_dir.parent.parent / "node"]
    if sys.platform == "win32":
        rel_path = Path("opencode.cmd")
    else:
        rel_path = Path("bin") / "opencode"
    for cand in candidates:
        opencode_path = cand / rel_path
        if opencode_path.exists():
            _ensure_opencode_binary(cand)  # self-heal the shim's target .exe
            return opencode_path
    return None


def build_opencode_command(opencode_bin: Path, args: list[str]) -> list[str]:
    """Wrap the bundled opencode binary for subprocess/PTY spawn.

    On Windows, opencode is a .cmd shim (npm's global-install convention),
    not a native .exe - CreateProcess can't exec a .cmd directly, so it
    needs the same `cmd.exe /c` wrapping every .cmd invocation needs.
    """
    if sys.platform == "win32":
        return ["cmd.exe", "/c", str(opencode_bin), *args]
    return [str(opencode_bin), *args]
