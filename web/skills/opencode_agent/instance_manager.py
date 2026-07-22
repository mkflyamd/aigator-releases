"""OpenCode server instance lifecycle — one `opencode serve` process per project.

Mirrors the persistence / startup-recovery patterns in
skills/code_agent/engine.py (CodeAgentSession, _persist_session,
_mark_stale_sessions_done), adapted for owning a real subprocess instead of
an in-process thread. See docs/internal/OpenCodeIntegrationPlan.md §1.

A project's OpenCode session data is disk-backed inside OpenCode's own
per-directory store, not tied to any particular server process — verified
directly: killing a live `opencode serve` process and starting a fresh one
against the same project directory recovers full session history. That's
what makes the idle-timeout reap in this module safe to be aggressive about:
reaping only frees resources, it never loses conversation state.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

_log = logging.getLogger(__name__)

_INSTANCE_DIR = Path.home() / ".gator" / "opencode" / "instances"
_LOG_DIR = Path.home() / ".gator" / "opencode" / "logs"
_LOG_MAX_BYTES = 2 * 1024 * 1024  # rotate the per-instance serve log past ~2MB
_PORT_RANGE = range(8100, 8200)
IDLE_TIMEOUT_SECONDS = 30 * 60
REAP_INTERVAL_SECONDS = 5 * 60

# Every project's subagents route through this model regardless of the
# project's main model choice — confirmed working end-to-end (explore fired
# on gator-gateway/gpt-4.1 while the main session used a different model).
# See OpenCodeIntegrationPlan.md §3.
EXPLORE_SUBAGENT_MODEL = "gator-gateway/gpt-4.1"

_instances: dict[str, "OpencodeServerInstance"] = {}

# Per-project spawn locks. ensure_instance() runs in a worker thread (callers
# await it via a thread pool), so concurrent warm/dispatch/terminal calls for
# the same project genuinely execute in parallel. Without serialization they
# all see "no instance yet" at once and each spawns its own `opencode serve` -
# the real bug that leaked 5 duplicate servers for one project and helped
# exhaust the thread pool. A threading.Lock (not asyncio.Lock: this is thread-
# land, not the event loop) per project makes check-then-spawn atomic so the
# first caller spawns and the rest wait and reuse. Keyed per project so
# different projects still spawn concurrently. _spawn_locks_guard only guards
# the tiny get-or-create of the per-project lock itself.
_spawn_locks: dict[str, threading.Lock] = {}
_spawn_locks_guard = threading.Lock()


def _get_spawn_lock(project_id: str) -> threading.Lock:
    with _spawn_locks_guard:
        lock = _spawn_locks.get(project_id)
        if lock is None:
            lock = _spawn_locks[project_id] = threading.Lock()
        return lock


# ── Registry v2: ownership + authoritative liveness (see plan A-done-right rev4) ──

_own_port_cache: int | None = None


def _reaper_v2_enabled() -> bool:
    """Feature flag `opencode_reaper_v2` (global, ~/.gator/config.json). Default False.
    OFF = today's behavior (_mark_stale_instances_stopped + sweep_idle_instances).
    ON  = ownership-aware reconcile + reap_own_idle."""
    try:
        from config import load_config
        return bool(load_config().get("opencode_reaper_v2", False))
    except Exception:
        return False


def _own_port() -> int:
    """This Gator instance's identity = the port it serves on. Derived from the
    ALWAYS-present `--port` in uvicorn's argv (dev.ps1, dev-workbench.ps1,
    watchdog.py all pass it — verified), so ownership never depends on a
    separately-set env var that a launch path could omit. Falls back to
    GATOR_INSTANCE_PORT, then 8000 (the packaged app's port). Cached.

    Known limitation: a dev server left on the default :8000 shares ownership
    with the packaged app; run dev instances on a non-8000 port to isolate."""
    global _own_port_cache
    if _own_port_cache is not None:
        return _own_port_cache
    port = None
    argv = sys.argv
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            try:
                port = int(argv[i + 1]); break
            except ValueError:
                pass
        elif a.startswith("--port="):
            try:
                port = int(a.split("=", 1)[1]); break
            except ValueError:
                pass
    if port is None:
        env = os.environ.get("GATOR_INSTANCE_PORT", "")
        port = int(env) if env.isdigit() else 8000
    _own_port_cache = port
    _log.info("[opencode] this Gator instance owns port %s (for OpenCode server ownership)", port)
    return port


def _resolve_server_pid(port: int) -> int:
    """Resolve the REAL opencode.exe pid listening on `port` (NOT the cmd.exe
    shim, which exits while opencode keeps running). Verify its image is under
    the bundled node/ dir to guard against PID recycling. Returns 0 if
    unresolvable (liveness then falls back to the port+/config probe)."""
    try:
        import psutil
        for c in psutil.net_connections(kind="tcp"):
            if c.laddr and c.laddr.port == port and c.status == psutil.CONN_LISTEN and c.pid:
                try:
                    exe = os.path.normcase(os.path.realpath(psutil.Process(c.pid).exe()))
                    if (os.sep + "node" + os.sep) in exe and "opencode" in exe:
                        return c.pid
                except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                    continue
    except Exception:
        pass
    return 0


def _port_config_status(port: int, password: str) -> int:
    """GET /config on the opencode server; return the HTTP status (0 on connection
    failure). 200 = up+authed; 401 = up but wrong/missing password. Both prove the
    HTTP server is ALIVE; only 0 (connection refused) means dead."""
    import base64
    import urllib.request
    import urllib.error
    try:
        headers = {}
        if password:
            token = base64.b64encode(f"opencode:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        req = urllib.request.Request(f"http://127.0.0.1:{port}/config", headers=headers)
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code  # 401 etc. — server IS up
    except (urllib.error.URLError, OSError):
        return 0  # connection refused / no server


def _server_alive(rec: dict) -> bool:
    """LIVENESS (not readiness): is an opencode server process for this record
    still running? Uses the real server_pid+image, else a port probe where 200 OR
    401 both count as alive (a 401 proves the HTTP server is up — this correctly
    handles legacy password-less records). NEVER the shim pid."""
    spid = int(rec.get("server_pid", 0) or 0)
    if spid > 0 and _pid_alive(spid):
        try:
            import psutil
            exe = os.path.normcase(os.path.realpath(psutil.Process(spid).exe()))
            if (os.sep + "node" + os.sep) in exe and "opencode" in exe:
                return True
        except Exception:
            pass
    port = int(rec.get("port", 0) or 0)
    if port <= 0:
        return False
    return _port_config_status(port, rec.get("password", "")) in (200, 401)


def _server_ready(rec: dict) -> bool:
    """READINESS (stronger than liveness): the server answers /config 200 with the
    saved password — safe to hand to a caller. Used by adopt/reclaim, NOT by the
    reaper's liveness classification."""
    port = int(rec.get("port", 0) or 0)
    if port <= 0 or not rec.get("password"):
        return False
    return _port_config_status(port, rec["password"]) == 200


@dataclass
class OpencodeServerInstance:
    project_id: str
    repo_path: str
    port: int
    pid: int                    # the cmd.exe SHIM pid (for tree-kill only — NOT liveness)
    password: str
    status: str = "starting"   # starting | running | stopped | crashed
    last_activity: float = field(default_factory=time.time)  # WALL CLOCK (comparable across processes)
    owner_port: int = 0        # the Gator instance (its serve port) that owns this server
    server_pid: int = 0        # the REAL opencode.exe pid (0 if unresolved); use for liveness


# ── Persistence — mirrors engine.py's _persist_session/_load_persisted_session ──

def _persist_instance(inst: OpencodeServerInstance) -> None:
    try:
        _INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
        # Real bug found via user report: this used to withhold the password
        # ("regenerated on every fresh spawn, so a stale copy is useless") -
        # but that reasoning assumed the process always gets killed and
        # respawned whenever Gator's own bookkeeping is lost (e.g. a dev
        # hot-reload, or Gator itself restarting). If the real opencode
        # process is still alive and well, the "stale" password is exactly
        # what's needed to keep talking to it - withholding it forced an
        # unnecessary kill+respawn on every such event, which also handed out
        # a NEW password and could reuse the freed port for a DIFFERENT
        # project's next spawn, cross-wiring an already-attached client (401
        # Unauthorized) to a server that isn't even its own project's.
        # Security note: this password only authenticates a 127.0.0.1-only
        # port that dies with the process, on the same machine/user - a
        # strictly lower-value secret than the LLM gateway API key Gator
        # already stores in plaintext in this same ~/.gator/ tree.
        data = asdict(inst)
        (_INSTANCE_DIR / f"{inst.project_id}.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:
        _log.debug("_persist_instance failed: %s", exc)


def _load_persisted_instance(project_id: str) -> dict | None:
    try:
        p = _INSTANCE_DIR / f"{project_id}.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        if sys.platform == "win32":
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,  # no flashing console window
            )
            return str(pid) in r.stdout
        try:
            import os
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _mark_stale_instances_stopped() -> None:
    """On Gator startup, mark any persisted instance whose process is gone.

    Mirrors engine.py's _mark_stale_sessions_done(): a Gator restart kills
    every subprocess it owned, so any instance still marked running/starting
    on disk is definitively dead. Does not attempt to reuse the stale port —
    ensure_instance() will allocate a fresh one on next use.
    """
    try:
        if not _INSTANCE_DIR.exists():
            return
        for p in _INSTANCE_DIR.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("status") in ("running", "starting") and not _pid_alive(data.get("pid", -1)):
                    data["status"] = "stopped"
                    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                    _log.info(
                        "Marked stale OpenCode instance for project %s as stopped",
                        data.get("project_id", "?"),
                    )
            except Exception:
                pass
    except Exception:
        pass


# NOTE: _mark_stale_instances_stopped() is NO LONGER called at import. It checked
# the cmd.exe SHIM pid (which exits while opencode.exe lives) and so marked LIVE
# servers "stopped" on every reload — corrupting the records. It's now invoked
# from the app lifespan ONLY when the opencode_reaper_v2 flag is OFF (fallback);
# when ON, reconcile_own_records() (real-liveness) replaces it. See app.py.


# ── Port allocation — reuses watchdog.py's existing probe, new range ────────────

def _port_in_use(port: int) -> bool:
    from watchdog import _port_in_use as _check
    return _check(port)


def _allocate_port() -> int:
    for port in _PORT_RANGE:
        if not _port_in_use(port):
            return port
    raise RuntimeError(
        f"No free port available in the OpenCode instance range "
        f"({_PORT_RANGE.start}-{_PORT_RANGE.stop - 1})"
    )


# ── Bundled opencode binary resolution — mirrors proc_utils.ensure_bundled_node_on_path ──

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
    the first success (cached flag). MUST be called from a worker thread
    (OPENCODE_POOL), never the event loop — it spawns a subprocess."""
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
    needs the same `cmd.exe /c` wrapping every .cmd invocation needs. Shared
    by both the `serve` spawn (_spawn_instance) and the `attach` spawn
    (opencode_routes.py) so this platform detail lives in exactly one place.
    """
    if sys.platform == "win32":
        return ["cmd.exe", "/c", str(opencode_bin), *args]
    return [str(opencode_bin), *args]


# ── Config generation — mirrors run-opencode.ps1's verified config shape ────────

def _build_provider_config(profile: dict, models: list[str]) -> dict:
    """Build the opencode.json provider/model config for a project.

    Same shape verified throughout the spike: custom provider ids (not the
    built-in "anthropic"/"openai", which pull in unwanted catalog models),
    every model explicitly declared (OpenCode validates against its own
    catalog otherwise), enabled_providers as an allowlist so nothing else
    can bleed in regardless of ambient credentials on the machine.

    Explore-subagent pinning is opt-in (default off), NOT automatic. It was
    initially built as an unconditional default - pin `explore` to a
    reliable cloud model regardless of the user's main model choice, to
    dodge the on-prem concurrency wall. That silently overrides the user's
    model choice for a subagent that actually reads and reasons over real
    repo content: if someone picked an on-prem model specifically for data
    residency or compliance reasons, silently routing that same code to a
    cloud endpoint anyway defeats the point, with no disclosure. Reversed
    per explicit direction - correctness/privacy over convenience. Default
    behavior now: explore uses whatever the main model is, same as any
    other agent - on-prem risk (the original concurrency-wall failure mode)
    is accepted by default, not silently routed around.
    """
    api_key = profile.get("api_key", "")
    api_key_header = profile.get("api_key_header", "")
    anthropic_url = (profile.get("anthropic_url") or "").rstrip("/")
    if anthropic_url and not anthropic_url.endswith("/v1"):
        anthropic_url += "/v1"
    unified_url = (profile.get("base_url") or "").rstrip("/")
    if unified_url and not unified_url.endswith("/v1"):
        unified_url += "/v1"

    claude_models = [m for m in models if "claude" in m.lower()]
    other_models = [m for m in models if "claude" not in m.lower()]

    config = {
        "$schema": "https://opencode.ai/config.json",
        "enabled_providers": ["gator-anthropic", "gator-gateway"],
        "model": f"gator-anthropic/{claude_models[0]}" if claude_models else (
            f"gator-gateway/{other_models[0]}" if other_models else ""
        ),
        "provider": {
            "gator-anthropic": {
                "npm": "@ai-sdk/anthropic",
                "options": {
                    "baseURL": anthropic_url,
                    "apiKey": "{env:GATOR_OPENCODE_KEY}",
                    "headers": {api_key_header: "{env:GATOR_OPENCODE_KEY}"},
                },
                "models": {m: {"name": m} for m in claude_models},
            },
            "gator-gateway": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Gator AMD Gateway",
                "options": {
                    "baseURL": unified_url,
                    "apiKey": "{env:GATOR_OPENCODE_KEY}",
                    "headers": {api_key_header: "{env:GATOR_OPENCODE_KEY}"},
                },
                "models": {m: {"name": m} for m in other_models},
            },
        },
    }

    # Opt-in only - explicit per-profile setting, absent/False by default.
    # No settings UI for this yet; until one exists, this is set by hand-
    # editing ~/.gator/config.json's llm_profiles[] entry.
    if profile.get("opencode_pin_explore_subagent", False):
        config["agent"] = {"explore": {"model": EXPLORE_SUBAGENT_MODEL}}

    return config


def _write_project_config(repo_path: str, profile: dict, models: list[str]) -> None:
    config = _build_provider_config(profile, models)
    config_path = Path(repo_path) / "opencode.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Track A: single-source in-memory config injection ────────────────────────
# See docs/internal/OpenCodeConfigSingleSourceProposal.md (Track A, approved).
# Gator supplies its provider/model config to `opencode serve` via the
# OPENCODE_CONFIG_CONTENT env var instead of writing <repo>/opencode.json, so
# nothing is written into the user's repo. Guarded by the feature flag below.

def _inmemory_config_enabled() -> bool:
    """Track A feature flag `opencode_inmemory_config` (global, ~/.gator/config.json).
    Default True (product/security signed off on the Option-B policy — §A10). When
    False, the LEGACY path writes/overwrites <repo>/opencode.json (destructive);
    switching to False is a deliberate, never-automatic choice."""
    try:
        from config import load_config
        return bool(load_config().get("opencode_inmemory_config", True))
    except Exception:
        return True


def _repo_root_has_runnable_mcp(repo_path: str) -> bool:
    """Option B (§A6.1): True if the repo-root opencode.json defines an MCP that
    could be enabled — in which case Gator must NOT start OpenCode (project-defined
    MCP support is deferred to Track B). Conservative / fail-closed: block on
    enabled:true, an omitted `enabled` (may default to enabled), an odd shape, or an
    unparseable file. Only an explicitly and validly `enabled: false` entry is
    treated as non-running. Scoped to the repo-root file only (migration safeguard,
    not inherited-MCP governance)."""
    p = Path(repo_path) / "opencode.json"
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return True  # malformed / unreadable -> fail closed
    if not isinstance(data, dict):
        return True
    mcp = data.get("mcp")
    if mcp is None:
        return False
    if not isinstance(mcp, dict):
        return True  # unexpected shape -> fail closed
    for entry in mcp.values():
        if not isinstance(entry, dict) or entry.get("enabled") is not False:
            # non-dict, enabled:true, omitted enabled, or any non-False value
            return True
    return False


def _guard_spawn_size(config_content: str, cmd: list[str], env: dict) -> None:
    """§A3 platform-specific spawn-size guardrail. Raises RuntimeError on overflow.
    No file fallback (OPENCODE_CONFIG isn't precedence-equivalent). Windows counts
    UTF-16 code units; POSIX counts argv+envp bytes vs the queried ARG_MAX."""
    if sys.platform == "win32":
        units = len(config_content.encode("utf-16-le")) // 2
        if units >= 30000:
            raise RuntimeError(
                f"OpenCode configuration is too large to pass to the coding agent "
                f"({units} UTF-16 code units; limit ~30000). Reduce configured providers/models."
            )
        block_units = 1 + sum(len(k) + len(str(v)) + 2 for k, v in env.items())
        if block_units > 1_000_000:
            raise RuntimeError("OpenCode process environment is too large to launch.")
    else:
        try:
            argmax = os.sysconf("SC_ARG_MAX")
        except (ValueError, OSError, AttributeError):
            argmax = 2_097_152  # conservative fallback
        argv_bytes = sum(len(str(a).encode("utf-8")) + 1 for a in cmd)
        envp_bytes = sum(
            len(str(k).encode("utf-8")) + 1 + len(str(v).encode("utf-8")) + 1
            for k, v in env.items()
        )
        if argv_bytes + envp_bytes > int(argmax * 0.9):
            raise RuntimeError(
                "OpenCode launch environment exceeds the platform ARG_MAX limit. "
                "Reduce configured providers/models."
            )


def _log_safe_config_summary(config: dict, config_content: str) -> None:
    """§A5: structured safe summary — provider names, model id, size, hash. Never
    the full config, never secrets."""
    import hashlib
    providers = sorted((config.get("provider") or {}).keys())
    digest = hashlib.sha256(config_content.encode("utf-8")).hexdigest()[:12]
    _log.info(
        "OpenCode config injected in-memory: providers=%s model=%s size=%dB sha256=%s",
        providers, config.get("model", ""), len(config_content.encode("utf-8")), digest,
    )


# ── Spawn / lifecycle ────────────────────────────────────────────────────────

def _wait_until_ready(port: int, password: str, timeout: float = 30.0) -> bool:
    """Poll GET /config with the instance's Basic Auth credentials.

    Two bugs found via real testing, not assumed:
    1. An unauthenticated probe gets a 401 from a genuinely-up, correctly-
       secured server - that's not a crash, it's the security in §2 working.
       Authenticating the probe is what makes "ready" mean "ready", not just
       "port is open".
    2. /status on OpenCode's own server returns its bundled web UI shell
       (HTML), not a JSON health check - that's a different thing from
       Gator's own /status route. A 200 there only weakly signals readiness
       (a static file could serve before the API layer is up). /config is a
       real API endpoint returning actual JSON, a stronger and more correct
       readiness signal.
    """
    import base64
    import urllib.request
    import urllib.error

    token = base64.b64encode(f"opencode:{password}".encode()).decode()
    req_headers = {"Authorization": f"Basic {token}"}

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/config", headers=req_headers)
            with urllib.request.urlopen(req, timeout=1) as resp:
                if resp.status == 200:
                    json.loads(resp.read())  # confirm it's real, parseable API JSON
                    return True
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            pass
        # Tightened from 0.3s - shaves up to 200ms off the worst-case
        # detection lag once the server actually becomes ready, for free.
        # Still bounded by the same 15s overall timeout, just checked more
        # often within it.
        time.sleep(0.1)
    return False


def get_mcp_status(port: int, password: str, timeout: float = 10.0) -> dict:
    """Query OpenCode's own GET /mcp endpoint for per-server connection status.

    Real gap found via user report: a manually-edited MCP config (global
    opencode.jsonc, or a project one) has no effect on an already-running
    `opencode serve` process - it only reads MCP config once at startup. The
    resulting failure ("server unavailable") is easy for a user to miss since
    it only shows up if they go looking at OpenCode's own logs. GET /mcp
    (confirmed via OpenCode's own OpenAPI /doc - a real, documented endpoint,
    not scraped log text) returns a clean structured status per server, e.g.
    {"chrome-devtools": {"status": "connected"}} or
    {"chrome-devtools": {"status": "failed", "error": "..."}} - exactly what's
    needed to surface a plain-language "this MCP failed" banner instead of a
    silent trap. A local MCP can take a few seconds to spawn on first
    connect (e.g. a cold `npx` resolve), hence the more generous timeout than
    _wait_until_ready's readiness poll.

    Returns {} on any failure (network error, bad auth, timeout) - callers
    should treat that as "unknown", not "no MCPs configured".
    """
    import base64
    import urllib.request
    import urllib.error

    token = base64.b64encode(f"opencode:{password}".encode()).decode()
    req_headers = {"Authorization": f"Basic {token}"}
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/mcp", headers=req_headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read())
                return data if isinstance(data, dict) else {}
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        pass
    return {}


def _serve_log_path(project_id: str, port: int) -> Path:
    """Per-instance serve log, namespaced by port so two Gator instances on the
    same project_id don't collide on one file."""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in project_id)
    return _LOG_DIR / f"{safe}-{port}.log"


def _rotate_serve_log(log_path: Path) -> None:
    """Single pre-spawn rotation to bound growth. Wrapped so a peer-held log
    (Windows lock) never aborts the spawn."""
    try:
        if log_path.exists() and log_path.stat().st_size > _LOG_MAX_BYTES:
            old = log_path.with_suffix(log_path.suffix + ".old")
            try:
                if old.exists():
                    old.unlink()
            except OSError:
                pass
            os.replace(log_path, old)
    except OSError:
        pass  # a locked/held log must never block a spawn


def _read_log_tail(log_path: Path, max_chars: int = 800) -> str:
    """Read the tail of a serve log for surfacing a readiness failure. Opened
    share-read so it works while the child still holds the file (Windows)."""
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()[-max_chars:].strip()
    except OSError:
        return ""


def _spawn_instance(project_id: str, repo_path: str) -> OpencodeServerInstance:
    from llm.registry import get_active_profile, available_models

    opencode_bin = find_bundled_opencode()
    if not opencode_bin:
        raise RuntimeError(
            "OpenCode binary not found. Run WakeGator to install it, or reinstall the app."
        )
    # Preflight: fail fast with a clear error if the binary can't run, instead
    # of letting the readiness poll below hit a silent 30s timeout. Runs on this
    # worker thread (OPENCODE_POOL), never the event loop.
    _opencode_preflight(opencode_bin)

    profile = get_active_profile()
    if not profile.get("api_key"):
        raise RuntimeError("No API key configured — set one up in Gator's Settings first.")

    models = available_models()
    inmemory = _inmemory_config_enabled()

    # Track A / Option B (§A6.1): block startup if the repo-root opencode.json
    # defines a runnable MCP. Checked before allocating anything so a blocked
    # project spawns nothing. Only applies on the in-memory path (legacy overwrites
    # the file, so its MCPs never run anyway).
    if inmemory and _repo_root_has_runnable_mcp(repo_path):
        raise RuntimeError(
            "This project defines MCP servers in its opencode.json. Gator doesn't run "
            "project-defined MCPs yet — remove them (or set them enabled:false) to use the "
            "coding agent, or wait for MCP support."
        )

    port = _allocate_port()
    password = secrets.token_urlsafe(24)

    env = {**os.environ, "GATOR_OPENCODE_KEY": profile["api_key"], "OPENCODE_SERVER_PASSWORD": password}
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    # Per-instance log (not DEVNULL) so a startup failure is never invisible again.
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _serve_log_path(project_id, port)
    _rotate_serve_log(log_path)
    cmd = build_opencode_command(opencode_bin, ["serve", "--port", str(port)])

    if inmemory:
        # Track A: inject config in-memory; do NOT write the repo file.
        if (Path(repo_path) / "opencode.json").exists():
            # §A4: detect (never delete) an existing repo file; OpenCode still merges it.
            _log.warning(
                "Project %s has an existing opencode.json. Gator no longer writes it, but "
                "OpenCode still merges it — left untouched.", project_id,
            )
        config = _build_provider_config(profile, models)
        config_content = json.dumps(config, ensure_ascii=False)
        env["OPENCODE_CONFIG_CONTENT"] = config_content
        _guard_spawn_size(config_content, cmd, env)   # §A3 (raises before spawn on overflow)
        _log_safe_config_summary(config, config_content)  # §A5
    else:
        # Legacy path — DESTRUCTIVE: overwrites <repo>/opencode.json (see §A10).
        _write_project_config(repo_path, profile, models)

    # Open the log and hand its inheritable handle to the child, then close the
    # parent's copy immediately: CreateProcess/fork dups the handle into the
    # child at spawn, so the child keeps writing (survives a uvicorn --reload
    # that kills this worker) while Gator holds NO handle — no leak, and no
    # shell-redirect quoting to get wrong.
    log_fh = open(log_path, "a", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=repo_path,
            env=env,
            creationflags=flags,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
        )
    finally:
        log_fh.close()

    inst = OpencodeServerInstance(
        project_id=project_id,
        repo_path=repo_path,
        port=port,
        pid=proc.pid,          # shim pid (tree-kill only)
        password=password,
        status="starting",
        owner_port=_own_port(),
    )

    # 45s (not 30s) — a cold 173MB start can exceed 30s; warm is ~1s. Covers
    # virtually all cold starts so the first attempt usually just succeeds.
    if _wait_until_ready(port, password, timeout=45.0):
        inst.status = "running"
        inst.server_pid = _resolve_server_pid(port)  # real opencode.exe pid, post-ready
    else:
        # Do NOT terminate: the process may just be a slow cold start. Leave it
        # "starting"; the immediate retry's reclaim path (which uses real-server
        # readiness, not the shim pid) adopts it fast, and the reaper's
        # stuck-not-ready branch cleans it if it never comes up.
        inst.status = "starting"
        tail = _read_log_tail(log_path)
        _log.warning(
            "OpenCode instance for project %s not ready within 45s (left running for "
            "reclaim/retry). Serve log tail (%s):\n%s",
            project_id, log_path, tail or "(empty — serve produced no output)",
        )

    _instances[project_id] = inst
    _persist_instance(inst)
    return inst


def _terminate_instance(inst: OpencodeServerInstance) -> None:
    """Stop a running instance. Tree-kills the REAL opencode.exe (server_pid),
    NOT just the cmd.exe shim (inst.pid) — the shim usually exits while
    opencode.exe keeps running, so killing only the shim left the real server
    alive (the "restart didn't work" bug: force-restart taskkill'd a dead shim,
    the server survived on its port, and the respawn grabbed a new port →
    orphan + duplicate). Resolve server_pid from the port if not yet known."""
    server_pid = inst.server_pid
    if server_pid <= 0:
        server_pid = _resolve_server_pid(inst.port)
    # Kill the real server first, then the shim (belt) — both as process trees.
    for pid in (server_pid, inst.pid):
        if pid <= 0 or not _pid_alive(pid):
            continue
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(pid), "/T"], capture_output=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
                time.sleep(2)
                if _pid_alive(pid):
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                import signal
                os.kill(pid, signal.SIGTERM)
                time.sleep(2)
                if _pid_alive(pid):
                    os.kill(pid, signal.SIGKILL)
        except Exception as exc:
            _log.warning("Failed to terminate OpenCode pid %s: %s", pid, exc)


# ── Public API ───────────────────────────────────────────────────────────────

def get_instance(project_id: str) -> OpencodeServerInstance | None:
    return _instances.get(project_id)


def force_restart_instance(project_id: str, repo_path: str) -> OpencodeServerInstance:
    """Unconditionally kill this project's opencode serve process (if any,
    live or not) and spawn a fresh one, guaranteeing every config layer
    (global, project, ancestor, .opencode, plus Gator's own injected config)
    gets re-read from scratch.

    Deliberately distinct from ensure_instance()'s adopt-instead-of-kill
    behavior: adopting a healthy process is correct when GATOR forgot about
    it (a reload/restart) - the process itself is fine, nothing needs
    re-reading. This is the opposite, explicit case: the process IS running
    fine but its IN-MEMORY config is known/suspected stale (e.g. the user
    edited an MCP config file after the session started - OpenCode only
    reads MCP config once at startup, not live). There, adopting would just
    reconnect to the same stale process forever. This function is the
    escape hatch for that - a deliberate, user-triggered "start over".
    """
    with _get_spawn_lock(project_id):
        inst = _instances.pop(project_id, None)
        if inst is None:
            persisted = _load_persisted_instance(project_id)
            if persisted:
                inst = OpencodeServerInstance(
                    project_id=persisted["project_id"],
                    repo_path=persisted["repo_path"],
                    port=persisted["port"],
                    pid=persisted.get("pid", 0),
                    password=persisted.get("password", ""),
                    status=persisted.get("status", "running"),
                    owner_port=persisted.get("owner_port", 0) or _own_port(),
                    server_pid=persisted.get("server_pid", 0) or 0,
                )
        if inst is not None:
            # _terminate_instance now resolves + tree-kills the real server_pid,
            # so the old server actually dies before we respawn (fixes the
            # duplicate/orphan restart bug). Free its record too.
            _terminate_instance(inst)
            try:
                (_INSTANCE_DIR / f"{inst.project_id}.json").unlink()
            except OSError:
                pass
        return _spawn_instance(project_id, repo_path)


def ensure_instance(project_id: str, repo_path: str) -> OpencodeServerInstance:
    """Return a running instance for this project, spawning or silently
    resuming one if needed. This is the single entry point the dispatcher
    (web/routes/opencode_routes.py) calls — it never needs to know whether
    the result was already running, freshly spawned, or a resume after an
    idle reap. All three cases converge here.
    """
    # Fast path: already running. CHEAP check on the REAL opencode pid (never the
    # cmd.exe shim pid, which exits while opencode keeps running → the shim check
    # used to falsely report dead and trigger a duplicate respawn). No HTTP on the
    # hot path. server_pid==0 (unresolved) → fall through to the slow path's probe.
    inst = _instances.get(project_id)
    if inst and inst.status == "running" and inst.server_pid > 0 and _pid_alive(inst.server_pid):
        inst.last_activity = time.time()
        return inst

    # Slow path: serialize per project so concurrent callers don't each spawn.
    with _get_spawn_lock(project_id):
        inst = _instances.get(project_id)
        if inst and inst.status == "running" and inst.server_pid > 0 and _pid_alive(inst.server_pid):
            inst.last_activity = time.time()
            return inst

        # Reclaim a still-booting/running server rather than spawning a competitor.
        # Judge by REAL-SERVER READINESS (answers /config with the saved password),
        # NOT the shim pid — a cold 173MB start leaves the shim gone but opencode
        # coming up; the readiness probe is what tells us it's genuinely usable.
        if inst and inst.password and _server_ready({"port": inst.port, "password": inst.password}):
            inst.status = "running"
            if inst.server_pid <= 0:
                inst.server_pid = _resolve_server_pid(inst.port)
            inst.last_activity = time.time()
            _persist_instance(inst)
            return inst

        return _ensure_instance_locked(project_id, repo_path)


def _ensure_instance_locked(project_id: str, repo_path: str) -> OpencodeServerInstance:
    """Spawn-or-recover path, always run while holding the project's spawn
    lock (see ensure_instance). Split out only so the locking in the caller
    reads clearly; never call this directly."""
    # Not in memory, or memory says it's gone — check disk before assuming
    # this is a brand-new project (covers a Gator restart mid-session).
    persisted = _load_persisted_instance(project_id)
    if persisted:
        # A record exists - the server may still be alive from before a reload/
        # restart. Judge by REAL-SERVER READINESS (answers /config with the saved
        # password), NOT the shim pid (which exits while opencode lives). If ready,
        # ADOPT it - no kill, no new password, no port churn (avoids cross-wiring
        # an attached client to another project's server → 401).
        candidate = OpencodeServerInstance(
            project_id=persisted["project_id"],
            repo_path=persisted["repo_path"],
            port=persisted["port"],
            pid=persisted.get("pid", 0),
            password=persisted.get("password", ""),
            status="running",
            owner_port=persisted.get("owner_port", 0) or _own_port(),
            server_pid=persisted.get("server_pid", 0) or 0,
        )
        if candidate.password and _server_ready({"port": candidate.port, "password": candidate.password}):
            if candidate.server_pid <= 0:
                candidate.server_pid = _resolve_server_pid(candidate.port)
            candidate.last_activity = time.time()
            _instances[project_id] = candidate
            _persist_instance(candidate)
            _log.info(
                "Adopted still-ready OpenCode server for project %s (server_pid %s, port %s) "
                "after Gator's own bookkeeping was reset.",
                project_id, candidate.server_pid, candidate.port,
            )
            return candidate

        # Not ready (dead, wrong/missing password, or corrupted record) - clean it
        # up (best-effort tree-kill of the shim if still around) and respawn fresh.
        _log.info(
            "Persisted OpenCode record for project %s didn't answer readiness - "
            "terminating any remnant and respawning.", project_id,
        )
        if _server_alive({"server_pid": candidate.server_pid, "port": candidate.port,
                          "password": candidate.password}) or _pid_alive(candidate.pid):
            _terminate_instance(candidate)

    # Genuinely nothing alive — spawn fresh. If this project had a previous
    # session, OpenCode's own disk-backed session store (keyed by repo_path)
    # recovers it automatically; this module only owns the process, not the
    # conversation history.
    return _spawn_instance(project_id, repo_path)


async def sweep_idle_instances() -> None:
    """LEGACY reap loop (opencode_reaper_v2 flag OFF). Reaps only in-memory
    instances — orphans left by a --reload leak (that's what v2 fixes). Kept as
    the fallback path.
    """
    now = time.time()
    for project_id, inst in list(_instances.items()):
        if inst.status != "running":
            continue
        if now - inst.last_activity > IDLE_TIMEOUT_SECONDS:
            _log.info("Reaping idle OpenCode instance for project %s (port %s)", project_id, inst.port)
            _terminate_instance(inst)
            inst.status = "stopped"
            _persist_instance(inst)


# ── Registry v2 reconcile + reaper (flag ON) ──────────────────────────────────

_REAP_MAX_KILLS_PER_PASS = 8   # bound serial taskkill+sleep cost per reap cycle
_STARTING_STUCK_SECONDS = 90   # > the 45s readiness window, so a booting server isn't reaped mid-start


def _iter_records():
    """Yield (path, record_dict) for every persisted instance record."""
    try:
        if not _INSTANCE_DIR.exists():
            return
        for p in _INSTANCE_DIR.glob("*.json"):
            try:
                yield p, json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
    except Exception:
        return


def _terminate_record(rec: dict) -> None:
    """Tree-kill an opencode server described by a record: prefer the real
    server_pid (the shim may be gone), fall back to the shim pid."""
    for pid in (int(rec.get("server_pid", 0) or 0), int(rec.get("pid", 0) or 0)):
        if pid > 0 and _pid_alive(pid):
            try:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    import signal
                    os.kill(pid, signal.SIGKILL)
            except Exception as exc:
                _log.debug("terminate_record pid %s failed: %s", pid, exc)


def reconcile_own_records() -> None:
    """Startup reconcile (flag ON), replaces the shim-pid-based
    _mark_stale_instances_stopped. Removes DEAD own/legacy records (including the
    corrupted 'stopped' ones the old marker wrote for live servers) using REAL
    liveness. Leaves ALIVE records alone — ensure_instance adopts them on demand
    (and stamps owner_port), avoiding any risky cross-instance legacy grab."""
    own = _own_port()
    for path, rec in _iter_records():
        rec_owner = int(rec.get("owner_port", 0) or 0)
        if rec_owner not in (own, 0):   # 0 = legacy/unknown (consider); else must be mine
            continue
        if _server_alive(rec):
            continue  # live — leave for on-demand adoption (never blind-adopt a legacy peer record)
        try:
            path.unlink()
            _log.info("[opencode-reconcile] removed dead record %s (owner %s)", path.name, rec_owner)
        except OSError:
            pass


def reap_own_idle() -> None:
    """v2 reaper (flag ON), SYNC — invoke via `await asyncio.to_thread(reap_own_idle)`
    (it does blocking psutil/taskkill). Own-only: touches ONLY records whose
    owner_port == this instance's port. Never peers/unknown → no cross-instance
    kill. Fixes the reload-orphan pile-up (own reload leftovers ARE own-owned)."""
    own = _own_port()
    now = time.time()
    killed = 0
    for path, rec in _iter_records():
        if int(rec.get("owner_port", 0) or 0) != own:
            continue  # own-only; legacy(0)/peer left alone (reconcile cleans dead legacy; stop.ps1 peers)
        project_id = rec.get("project_id", "")
        if not _server_alive(rec):
            try:
                path.unlink()
                _instances.pop(project_id, None)
            except OSError:
                pass
            continue
        if killed >= _REAP_MAX_KILLS_PER_PASS:
            continue
        age = now - float(rec.get("last_activity", 0) or 0)
        ready = _server_ready(rec)
        reap = False
        if not ready:
            # stuck "starting" that never became usable
            reap = age > _STARTING_STUCK_SECONDS
        else:
            reap = age > IDLE_TIMEOUT_SECONDS
        if not reap:
            continue
        lock = _get_spawn_lock(project_id)
        if not lock.acquire(blocking=False):
            continue  # a spawn/adopt is in progress → not idle, skip
        try:
            _log.info("[opencode-reap] reaping own %s server for %s (port %s, ready=%s, idle=%ss)",
                      "idle" if ready else "stuck", project_id, rec.get("port"), ready, int(age))
            _terminate_record(rec)
            _instances.pop(project_id, None)
            try:
                path.unlink()
            except OSError:
                pass
            killed += 1
        finally:
            lock.release()

