"""Generic terminal-based coding agents (Claude Code CLI, Codex CLI, Crush,
...) — an alternative to OpenCode for users who already have one of these
installed and configured with their own provider/API keys.

Deliberately the opposite of instance_manager.py's OpenCode integration:
- No bundled binary, no self-heal, no version pinning — BYO install, resolved
  via PATH (shutil.which) same as running it in a normal terminal.
- No server/health-check lifecycle — these are single foreground processes
  per session, not a `serve` + `attach` split like OpenCode.
- No config injection — the tool reads its own native config exactly as it
  would outside Gator. Gator only decides WHICH command to spawn and WHERE
  (repo_path as cwd); everything else is the tool's own business.

This intentionally does not share code with instance_manager.py/
opencode_routes.py — OpenCode's path is deliberately left untouched to avoid
any regression risk to it while this is being built out.

OPENCODE_BARE_AGENT is the one deliberate exception to the "no config
injection" rule above: it's a same-machine A/B test of instance_manager.py's
`opencode serve` + `opencode attach` split against a single bare `opencode`
process (issue #156 — repeated "connection problem" disconnects that don't
reproduce with a bare process, standalone or through Gator's own terminal
bridge, only with the serve+attach split). It reuses instance_manager's
config-building helpers to talk to the same gateway, but is otherwise spawned
exactly like Claude/Codex/Crush: one foreground process, no server, no
health-check, no --session resume across a lost PTY (same v1 tradeoff already
accepted below for the other agents).
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

# name -> argv. Extend here to add a new agent; no other file needs to know
# the executable name. Values are lists (not a bare string) so a future entry
# needing fixed flags (e.g. a non-interactive/resume flag) can just add them.
SUPPORTED_AGENTS: dict[str, list[str]] = {
    "claude": ["claude"],
    "codex": ["codex"],
    "crush": ["crush"],
}

# Further terminal agents, using Orca's agent catalog (stablyai/orca, MIT) for
# ids and executable names: id -> (label, argv, alternate executable names).
# They are plain PATH-resolved terminals with no gateway wiring, and the "+"
# menu lists one only when it is installed. OpenCode is the PATH-resolved, gateway-
# routed "opencode-bare" agent, so there are no separate opencode entries here. Orca's workspace-trust flags
# (command-code --trust, muse --trust-workspace) are deliberately left out.
EXTRA_AGENTS: dict[str, tuple[str, list[str], tuple[str, ...]]] = {
    "openclaude": ("OpenClaude", ["openclaude"], ()),
    "grok": ("Grok", ["grok"], ()),
    "copilot": ("GitHub Copilot", ["copilot"], ()),
    "mimo-code": ("MiMo Code", ["mimo"], ()),
    "ante": ("Ante", ["ante"], ()),
    "trae": ("Trae", ["traecli"], ()),
    "muse": ("Muse", ["muse"], ()),
    "dsh": ("DeepSeek Harness", ["dsh-tui", "."], ("dst",)),
    "qoder": ("Qoder CLI", ["qodercli"], ("qoder",)),
    "qoder-cn": ("Qoder CLI China", ["qoderclicn"], ("qodercn",)),
    "zcode": ("ZCode", ["zcode"], ()),
    "pi": ("Pi", ["pi"], ()),
    "omp": ("OMP", ["omp"], ()),
    "prime-agent": ("Prime Agent", ["prime-agent"], ()),
    "gemini": ("Gemini", ["gemini"], ()),
    "antigravity": ("Antigravity", ["agy"], ()),
    "aider": ("Aider", ["aider"], ()),
    "goose": ("Goose", ["goose"], ()),
    "amp": ("Amp", ["amp"], ()),
    "kilo": ("Kilocode", ["kilo"], ()),
    "kiro": ("Kiro", ["kiro-cli", "chat", "--tui"], ()),
    "aug": ("Auggie", ["auggie"], ()),
    "autohand": ("Autohand Code", ["autohand"], ()),
    "cline": ("Cline", ["cline"], ()),
    "codebuff": ("Codebuff", ["codebuff"], ()),
    "freebuff": ("Freebuff", ["freebuff"], ()),
    "command-code": ("Command Code", ["command-code"], ()),
    "continue": ("Continue", ["cn"], ()),
    "cursor": ("Cursor", ["cursor-agent"], ()),
    "droid": ("Droid", ["droid"], ()),
    "kimi": ("Kimi", ["kimi"], ("kimi-code",)),
    "mistral-vibe": ("Mistral Vibe", ["vibe"], ("mistral-vibe",)),
    "qwen-code": ("Qwen Code", ["qwen"], ()),
    "rovo": ("Rovo Dev", ["acli", "rovodev", "run"], ()),
    "hermes": ("Hermes", ["hermes", "--tui"], ()),
    "devin": ("Devin", ["devin"], ()),
    "openclaw": ("OpenClaw", ["openclaw"], ()),
    "codebuddy": ("CodeBuddy", ["codebuddy"], ("cbc",)),
    "jcode": ("JCode", ["jcode"], ()),
}
SUPPORTED_AGENTS.update({agent: argv for agent, (_, argv, _) in EXTRA_AGENTS.items()})
EXTRA_AGENT_LABELS: dict[str, str] = {agent: label for agent, (label, _, _) in EXTRA_AGENTS.items()}

# A bare shell in the project directory - the maximally-flexible fallback for
# a tool not in SUPPORTED_AGENTS (or no tool at all), rather than maintaining
# an ever-growing fixed list. Not in SUPPORTED_AGENTS since it needs no
# binary resolution at all - it's just create_pty_session(command=None) with
# cwd set to the project, identical to what the general terminal.js panel
# already spawns, just scoped to a specific repo instead of Gator's own cwd.
TERMINAL_AGENT = "terminal"

# Bare-process OpenCode (see module docstring). Not in SUPPORTED_AGENTS since it
# needs Gator's gateway config injected via env - build_opencode_bare_command/
# _env below handle both. The binary is PATH-resolved like claude/codex/crush.
OPENCODE_BARE_AGENT = "opencode-bare"


CORE_AGENT_LABELS = {
    "claude": "Claude Code",
    "codex": "Codex",
    "crush": "Crush",
    OPENCODE_BARE_AGENT: "OpenCode",
}
# Agents whose launch always injects the AI Gator gateway config. Claude Code is
# routed when the profile has an Anthropic endpoint, and Codex when its own
# config already points at the gateway; everything else runs on whatever
# configuration the user already has.
GATEWAY_ROUTED = frozenset({"crush", OPENCODE_BARE_AGENT})


def agent_label(agent: str) -> str:
    if agent == TERMINAL_AGENT:
        return "Terminal"
    return CORE_AGENT_LABELS.get(agent) or EXTRA_AGENT_LABELS.get(agent) or agent


def is_gateway_routed(agent: str) -> bool:
    if agent in GATEWAY_ROUTED:
        return True
    if agent == "codex":
        from llm.registry import get_active_profile

        return codex_config_routes_to_gateway(get_active_profile())
    return effective_binding(agent) is not None


def handoff_targets() -> list[dict]:
    """Every agent a session can be continued in: the core agents (listed even
    when missing, so the dialog can say so) then the other catalog agents that
    are installed."""
    targets = []
    for a in [*CORE_AGENT_LABELS, *EXTRA_AGENTS]:
        installed = is_installed(a)
        if installed or a in CORE_AGENT_LABELS:
            targets.append(
                {
                    "agent": a,
                    "label": agent_label(a),
                    "gateway_routed": is_gateway_routed(a),
                    "installed": installed,
                }
            )
    return targets


def is_supported(agent: str) -> bool:
    return agent in SUPPORTED_AGENTS or agent == TERMINAL_AGENT or agent == OPENCODE_BARE_AGENT


def is_bare_terminal(agent: str) -> bool:
    return agent == TERMINAL_AGENT


def is_opencode_bare(agent: str) -> bool:
    return agent == OPENCODE_BARE_AGENT


def find_agent_binary(agent: str) -> str | None:
    """Resolve the agent's binary on PATH. None if not installed - the route
    layer turns this into a clear "not installed" error rather than a
    confusing PTY that dies instantly."""
    argv = SUPPORTED_AGENTS.get(agent)
    if not argv:
        return None
    aliases = EXTRA_AGENTS[agent][2] if agent in EXTRA_AGENTS else ()
    for name in (argv[0], *aliases):
        found = shutil.which(name)
        if found:
            return found
    return None


# Agents installed inside WSL rather than on the Windows PATH. Crush is left out
# because its gateway config is a Windows file path; OpenCode is not in
# SUPPORTED_AGENTS at all.
_WSL_TTL_SECONDS = 60
_WSL_PROBE_TIMEOUT = 20
_wsl_cache: tuple[float, tuple[str | None, dict[str, str]]] = (0.0, (None, {}))
_wsl_first_probe = threading.Lock()


def _wsl_capable(agent: str) -> bool:
    return agent in SUPPORTED_AGENTS and agent != "crush"


def _wsl_run(args: list[str], script: str | None = None) -> str | None:
    try:
        proc = subprocess.run(
            ["wsl.exe", *args],
            input=script.encode() if script is not None else None,
            capture_output=True,
            timeout=_WSL_PROBE_TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.decode("utf-8", "replace") if proc.returncode == 0 else None


def _wsl_default_distro() -> str | None:
    # `wsl -l` writes UTF-16, so it is decoded from the raw bytes.
    try:
        proc = subprocess.run(
            ["wsl.exe", "-l", "-q"],
            capture_output=True,
            timeout=_WSL_PROBE_TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for name in proc.stdout.decode("utf-16-le", "replace").lstrip("\ufeff").split():
        if not name.startswith("docker-desktop"):
            return name
    return None


def _wsl_probe() -> tuple[str | None, dict[str, str]]:
    """(distro, {agent id: executable name}) for catalog agents found inside the
    default WSL distro. Hits under /mnt are the Windows PATH leaking in, which the
    Windows lookup already covers."""
    if sys.platform != "win32" or not shutil.which("wsl.exe"):
        return None, {}
    distro = _wsl_default_distro()
    if not distro:
        return None, {}
    names: dict[str, str] = {}
    for agent in SUPPORTED_AGENTS:
        if _wsl_capable(agent):
            for name in (SUPPORTED_AGENTS[agent][0], *(EXTRA_AGENTS[agent][2] if agent in EXTRA_AGENTS else ())):
                names[name] = agent
    script = 'for n in %s; do p=$(command -v "$n") && echo "$n=$p"; done; exit 0' % " ".join(shlex.quote(n) for n in names)
    # A cold distro can return nothing on the first call, so try twice.
    out = ""
    for _ in range(2):
        # The script goes in on stdin: wsl.exe runs its argv through a shell that
        # would expand the loop's $variables before bash sees them.
        out = _wsl_run(["-d", distro, "--", "bash", "-l"], script) or ""
        if "=" in out:
            break
    found: dict[str, str] = {}
    for line in out.splitlines():
        name, _, path = line.strip().partition("=")
        if name in names and path.startswith("/") and not path.startswith("/mnt/"):
            found.setdefault(names[name], name)
    return distro, found


_refresh_lock = threading.Lock()
_refreshing: set[str] = set()


def _stale_while_revalidate(key: str, refresh) -> None:
    """Re-run `refresh` off-thread so a caller holding an expired cache entry is
    never made to wait on a WSL cold start."""
    with _refresh_lock:
        if key in _refreshing:
            return
        _refreshing.add(key)

    def run():
        try:
            refresh()
        finally:
            with _refresh_lock:
                _refreshing.discard(key)

    threading.Thread(target=run, daemon=True, name=f"gator-{key}-refresh").start()


def _refresh_wsl_cache() -> None:
    global _wsl_cache
    _wsl_cache = (time.monotonic(), _wsl_probe())


def wsl_agents() -> tuple[str | None, dict[str, str]]:
    stamp, value = _wsl_cache
    if not stamp:
        with _wsl_first_probe:
            if not _wsl_cache[0]:
                _refresh_wsl_cache()
        return _wsl_cache[1]
    if time.monotonic() - stamp > _WSL_TTL_SECONDS:
        _stale_while_revalidate("wsl", _refresh_wsl_cache)
    return value


_codex_cfg_cache: tuple[float, str] = (0.0, "")


def _read_codex_config() -> str:
    if find_agent_binary("codex"):
        home = os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")
        try:
            return (Path(home) / "config.toml").read_text(encoding="utf-8")
        except OSError:
            return ""
    distro, found = wsl_agents()
    if distro and "codex" in found:
        return _wsl_run(
            ["-d", distro, "--", "bash"],
            'cat "${CODEX_HOME:-$HOME/.codex}/config.toml" 2>/dev/null; exit 0',
        ) or ""
    return ""


def _refresh_codex_config() -> None:
    global _codex_cfg_cache
    _codex_cfg_cache = (time.monotonic(), _read_codex_config())


def _codex_config_text() -> str:
    """The user's Codex config.toml: the Windows file when Codex is installed
    on Windows, otherwise the one inside the WSL distro that has it."""
    stamp, text = _codex_cfg_cache
    if not stamp:
        _refresh_codex_config()
        return _codex_cfg_cache[1]
    if time.monotonic() - stamp > _WSL_TTL_SECONDS:
        _stale_while_revalidate("codex-config", _refresh_codex_config)
    return text


def warm_agent_caches() -> None:
    """Probe WSL and read Codex's config in the background at startup, so the
    first "+" menu or handoff dialog does not pay for a WSL cold start."""
    def run():
        wsl_agents()
        _codex_config_text()

    threading.Thread(target=run, daemon=True, name="gator-agent-warmup").start()


def codex_config_routes_to_gateway(profile: dict) -> bool:
    """Whether Codex's own config selects a provider hosted on the profile's
    gateway (AMD's Codex build is set up this way and refuses other providers,
    so AI Gator leaves its launch alone)."""
    import tomllib
    from urllib.parse import urlparse

    gateway_hosts = {
        urlparse(profile.get(k) or "").hostname
        for k in ("base_url", "anthropic_url")
    } - {None}
    if not gateway_hosts:
        return False
    try:
        cfg = tomllib.loads(_codex_config_text())
    except tomllib.TOMLDecodeError:
        return False
    provider = (cfg.get("model_providers") or {}).get(cfg.get("model_provider", ""), {})
    return urlparse(provider.get("base_url") or "").hostname in gateway_hosts


def _wsl_command(agent: str, repo_path: str, resume_args: tuple[str, ...] = ()) -> list[str] | None:
    distro, found = wsl_agents()
    name = found.get(agent)
    if not distro or not name:
        return None
    argv = [name, *SUPPORTED_AGENTS[agent][1:], *resume_args]
    cmd = ["wsl.exe", "-d", distro]
    if repo_path:
        cmd += ["--cd", repo_path]
    return [*cmd, "--", "bash", "-lc", "exec " + shlex.join(argv)]


def is_installed(agent: str) -> bool:
    """Whether this agent can be spawned right now. The Windows PATH is checked
    per call so an agent installed mid-session shows up without a restart; WSL is
    probed in the background at most once a minute because it can boot the distro."""
    if agent == TERMINAL_AGENT:
        return True
    if agent == OPENCODE_BARE_AGENT:
        return build_opencode_bare_command("") is not None
    if find_agent_binary(agent) is not None:
        return True
    return _wsl_capable(agent) and agent in wsl_agents()[1]


def launchable_agents() -> list[str]:
    core = [a for a in SUPPORTED_AGENTS if a not in EXTRA_AGENTS]
    return [*core, OPENCODE_BARE_AGENT, TERMINAL_AGENT, *EXTRA_AGENTS]


def build_command(agent: str, repo_path: str = "", extra_args: tuple[str, ...] = ()) -> list[str] | None:
    """Full argv to spawn for this agent, with the resolved absolute binary
    path in place of the bare name (matches OpenCode's own build_opencode_
    command pattern of never relying on child-process PATH resolution)."""
    argv = SUPPORTED_AGENTS.get(agent)
    if not argv:
        return None
    resolved = find_agent_binary(agent)
    if not resolved:
        return _wsl_command(agent, repo_path) if _wsl_capable(agent) else None
    return [resolved, *argv[1:], *extra_args]


_RESUME_VERBS = {"claude": ("--resume",), "codex": ("resume",)}


def build_resume_command(
    agent: str,
    repo_path: str,
    session_id: str,
    source: str = "windows",
    extra_args: tuple[str, ...] = (),
) -> list[str] | None:
    """argv that reopens a stored session in the agent's own resume mode, in the
    place the session lives. A WSL session resumes inside its distro with the
    Linux path, never a UNC path."""
    verb = _RESUME_VERBS.get(agent)
    if not verb:
        return None
    if source == "windows":
        resolved = find_agent_binary(agent)
        if not resolved:
            return None
        return [resolved, *SUPPORTED_AGENTS[agent][1:], *extra_args, *verb, session_id]
    distro, _found = wsl_agents()
    if not distro or source != f"wsl:{distro}":
        return None
    return _wsl_command(agent, repo_path, (*verb, session_id))


# (project_id, agent) -> pty_session_id of that project+agent's current
# terminal. In-memory only (unlike OpenCode's disk-backed instance registry) —
# a server restart just means "no known session to resume", which for a
# single-foreground-process tool with no server-side state to reconnect to is
# a reasonable v1 tradeoff, not a regression against anything that exists
# today.
#
# Real bug found via user report: this was keyed by project_id ALONE. A
# project switched from Claude to Terminal (or vice versa) would still find
# the OTHER agent's still-alive session under that same project_id key and
# silently reattach to it - "Start Claude" would hand back a live PowerShell
# PTY, or switching away from Claude to anything else would just reload
# Claude again, regardless of what was actually requested. The agent must be
# part of the identity of "this project's active session", not just the
# project - each agent has its own independent process per project.
_active_sessions: dict[tuple[str, str], str] = {}


def get_active_session(project_id: str, agent: str) -> str | None:
    return _active_sessions.get((project_id, agent))


def set_active_session(project_id: str, agent: str, pty_session_id: str) -> None:
    _active_sessions[(project_id, agent)] = pty_session_id


def clear_active_session(project_id: str, agent: str) -> None:
    _active_sessions.pop((project_id, agent), None)


def new_session_id() -> str:
    return str(uuid.uuid4())


# Claude Code is launched with a session id Gator chose, so a handoff reads that
# conversation's transcript and not whichever one in the folder is newest.
_pinned_sessions: dict[str, str] = {}


# Every terminal whose stored session Gator knows (resumed, or a WSL Claude launch), whatever
# the agent, so the history panel can link it. Kept apart from _pinned_sessions, which handoff
# reads for native Claude only.
_linked_sessions: dict[str, tuple[str, str]] = {}


def pin_session(agent: str, command: list[str], pty_session_id: str) -> list[str]:
    if agent != "claude" or not command:
        return command
    transcript_id = str(uuid.uuid4())
    if Path(command[0]).stem.lower() == "wsl":
        # Handoff keeps looking WSL transcripts up unpinned; only the history link is recorded.
        if command[-2:-1] != ["-lc"]:
            return command
        _linked_sessions[pty_session_id] = (agent, transcript_id)
        return [*command[:-1], f"{command[-1]} --session-id {transcript_id}"]
    _pinned_sessions[pty_session_id] = transcript_id
    return [*command, "--session-id", transcript_id]


def pin_resume(agent: str, command: list[str], pty_session_id: str, session_id: str) -> list[str]:
    if command:
        _linked_sessions[pty_session_id] = (agent, session_id)
        if agent == "claude" and Path(command[0]).stem.lower() != "wsl":
            _pinned_sessions[pty_session_id] = session_id
    return command


def pinned_session_id(pty_session_id: str) -> str | None:
    return _pinned_sessions.get(pty_session_id)


def linked_session_id(pty_session_id: str) -> str | None:
    linked = _linked_sessions.get(pty_session_id)
    return linked[1] if linked else _pinned_sessions.get(pty_session_id)


def ptys_for_session(agent: str, session_id: str) -> list[str]:
    found = [pty for pty, (a, sid) in _linked_sessions.items() if a == agent and sid == session_id]
    if agent == "claude":
        found += [pty for pty, sid in _pinned_sessions.items() if sid == session_id and pty not in found]
    return found


def unpin_session(pty_session_id: str) -> None:
    _pinned_sessions.pop(pty_session_id, None)
    _linked_sessions.pop(pty_session_id, None)


def build_opencode_bare_command(repo_path: str) -> list[str] | None:
    """argv for a single bare `opencode` process rooted at repo_path — no
    `serve`, no `attach`. None if opencode can't be found (mirrors
    build_command's contract for the route layer's "not installed" error).

    Resolved on PATH via shutil.which("opencode"), same as claude/codex/crush -
    install with `npm install -g opencode-ai`. AI Gator does not bundle or pin it.

    No --session resume: a lost/restarted PTY just starts a fresh OpenCode
    session, same tradeoff _active_sessions already documents for every other
    agent here.
    """
    import shutil

    resolved = shutil.which("opencode")
    if resolved:
        return [_wrap_windows_cmd(resolved), repo_path]
    return None


def _wrap_windows_cmd(path: str) -> str:
    """Return an argv[0] safe for PtyProcess.spawn.

    shutil.which("opencode") on Windows can return a .cmd/.bat shim (npm global
    installs are .cmd). PtyProcess.spawn can exec those directly here because the
    caller wraps the command list, but we normalise to the resolved path so the
    child never re-resolves the bare name through PATH (which could hit a
    different shim). Kept trivial and platform-agnostic on purpose.
    """
    return path


def build_opencode_bare_env() -> dict[str, str]:
    """OPENCODE_CONFIG_CONTENT + GATOR_OPENCODE_KEY for the bare process,
    built from the same active LLM profile instance_manager.py uses for the
    real serve+attach path — so this is an apples-to-apples A/B test of the
    process split, not a different gateway/model setup.

    Deliberately simpler than instance_manager._build_provider_config: no
    gpt-5/Responses-API provider (skipped — irrelevant to the Claude/gateway
    connectivity issue this is testing). Raises RuntimeError with the same
    "no API key configured" message instance_manager uses if the profile
    isn't set up, so the route layer's existing error handling applies as-is.
    """
    from llm.registry import get_active_profile, available_models

    profile = get_active_profile()
    if not profile.get("api_key"):
        raise RuntimeError("No API key configured — set one up in Gator's Settings first.")

    models = available_models()
    api_key_header = profile.get("api_key_header", "")
    anthropic_url = (profile.get("anthropic_url") or "").rstrip("/")
    if anthropic_url and not anthropic_url.endswith("/v1"):
        anthropic_url += "/v1"
    unified_url = (profile.get("base_url") or "").rstrip("/")
    if unified_url and not unified_url.endswith("/v1"):
        unified_url += "/v1"

    claude_models = [m for m in models if "claude" in m.lower()]
    other_models = [m for m in models if "claude" not in m.lower()]

    def _model_ref(m: str) -> str:
        return f"gator-anthropic/{m}" if "claude" in m.lower() else f"gator-gateway/{m}"

    active = profile.get("active_model", "")
    default_model = _model_ref(active) if active in models else (
        _model_ref(claude_models[0]) if claude_models else
        (_model_ref(other_models[0]) if other_models else "")
    )

    # attachment + modalities.input ["image"] on every model entry — custom
    # provider ids deliberately bypass OpenCode's built-in model catalog (same
    # reason as instance_manager._build_provider_config), which is also where
    # OpenCode would normally learn a model supports image input. `attachment`
    # alone only enables the attach button; the runtime image-read check tests
    # capabilities.input.image, which OpenCode derives from
    # modalities.input containing "image" (no fallback for unknown providers).
    # Without modalities, OpenCode refuses image reads even though every Gator
    # LLM provider already declares supports_vision = True (llm/base.py,
    # llm/anthropic_provider.py).
    #
    # options.thinking.blockBinding = False on every Claude model: OpenCode
    # auto-enables Anthropic's "adaptive thinking" block-binding beta
    # (thinking.block_binding on the wire) for Claude models whose version is
    # 5.1+ (e.g. Claude-Sonnet-5.5), but AMD's Anthropic-native gateway
    # rejects that field with "thinking.adaptive.block_binding: Extra inputs
    # are not permitted" (confirmed directly against the real gateway with
    # the official anthropic Python SDK - thinking:{type:"adaptive"} alone
    # works, adding block_binding fails every time, with or without the
    # anthropic-beta header). blockBinding=false is OpenCode's opt-out; it
    # strips block_binding before the wire. Verified end-to-end against the
    # real gateway through opencode itself (isolated from this machine's
    # ambient OPENCODE_CONFIG_CONTENT env var, which otherwise silently
    # shadows custom providers and produces misleading errors that look
    # like a config/compat problem but aren't): Claude-Sonnet-5,
    # Claude-Sonnet-5.5, and Claude-Haiku-4.5 all responded successfully
    # with this option set, including against the global npm install, so it's safe on every Claude model.
    provider = {}
    enabled_providers = []
    if claude_models:
        enabled_providers.append("gator-anthropic")
        provider["gator-anthropic"] = {
            "npm": "@ai-sdk/anthropic",
            "options": {
                "baseURL": anthropic_url,
                "apiKey": "{env:GATOR_OPENCODE_KEY}",
                "headers": {api_key_header: "{env:GATOR_OPENCODE_KEY}"},
            },
            "models": {m: {"name": m, "attachment": True,
                           "modalities": {"input": ["text", "image"], "output": ["text"]},
                           "options": {"thinking": {"blockBinding": False}}}
                       for m in claude_models},
        }
    if other_models:
        enabled_providers.append("gator-gateway")
        provider["gator-gateway"] = {
            "npm": "@ai-sdk/openai-compatible",
            "name": "Gator AMD Gateway",
            "options": {
                "baseURL": unified_url,
                "apiKey": "{env:GATOR_OPENCODE_KEY}",
                "headers": {api_key_header: "{env:GATOR_OPENCODE_KEY}"},
            },
            "models": {m: {"name": m, "attachment": True,
                           "modalities": {"input": ["text", "image"], "output": ["text"]}}
                       for m in other_models},
        }

    import json
    config = {
        "$schema": "https://opencode.ai/config.json",
        "enabled_providers": enabled_providers,
        "model": default_model,
        "provider": provider,
    }
    return {
        "OPENCODE_CONFIG_CONTENT": json.dumps(config, ensure_ascii=False),
        "GATOR_OPENCODE_KEY": profile["api_key"],
    }


_CRUSH_CONFIG_DIR = Path.home() / ".gator" / "crush"


def _build_crushrc(profile: dict, models: list[str]) -> str:
    """Generate a crushrc from the active Gator LLM profile.

    Mirrors setup_standalone_crush_llm.ps1's verified config shape: custom
    provider ids (gator-anthropic for Claude, gator-gateway for everything
    else), every model explicitly declared, default-providers off so nothing
    bleeds in from ambient credentials. Crush has no env-content equivalent of
    OPENCODE_CONFIG_CONTENT, so the crushrc is written to a file under
    ~/.gator/crush/ and the directory is injected via CRUSH_GLOBAL_CONFIG.

    URL convention difference from OpenCode (verified empirically against
    this gateway — see the standalone script): Crush's Go Anthropic client
    appends /v1/messages itself, so the Anthropic base URL must NOT include
    /v1. The OpenAI-compat client expects /v1 in the base URL.
    """
    api_key_header = profile.get("api_key_header", "")
    # Anthropic URL: NO /v1 suffix (Crush's Go client appends /v1/messages).
    anthropic_url = (profile.get("anthropic_url") or "").rstrip("/")
    if anthropic_url.endswith("/v1"):
        anthropic_url = anthropic_url[:-3]
    # Gateway URL: /v1 suffix required (openai-compat client).
    unified_url = (profile.get("base_url") or "").rstrip("/")
    if unified_url and not unified_url.endswith("/v1"):
        unified_url += "/v1"

    claude_models = [m for m in models if "claude" in m.lower()]
    other_models = [m for m in models if "claude" not in m.lower()]

    def _model_ref(m: str) -> str:
        return f"gator-anthropic/{m}" if "claude" in m.lower() else f"gator-gateway/{m}"

    active = profile.get("active_model", "")
    if active and active in models:
        default_ref = _model_ref(active)
    elif claude_models:
        default_ref = _model_ref(claude_models[0])
    elif other_models:
        default_ref = _model_ref(other_models[0])
    else:
        default_ref = ""

    haiku = next((m for m in claude_models if "haiku" in m.lower()), None)
    small_ref = _model_ref(haiku) if haiku else default_ref

    lines: list[str] = [
        "# Generated by AI Gator — do not edit by hand.",
        "# Regenerated on each Crush session start from the active LLM profile.",
        "",
    ]

    def _model_add_line(provider_id: str, model_id: str, is_claude: bool) -> str:
        can_reason = "true" if is_claude else "false"
        supports_images = "true" if model_id.lower().split("-")[0] in ("claude", "gpt", "gemini") else "false"
        escaped = model_id.replace('"', '\\"')
        return (
            f'model add {provider_id}/{model_id} --name "{escaped}" '
            f"--context-window 200000 --default-max-tokens 8000 "
            f"--can-reason {can_reason} --supports-images {supports_images} "
            f"--price-input 0 --price-output 0 --price-cache-create 0 --price-cache-hit 0"
        )

    if claude_models:
        lines += [
            "provider add gator-anthropic \\",
            "  --type anthropic \\",
            f'  --base-url "{anthropic_url}" \\',
            '  --api-key "$GATOR_CRUSH_KEY" \\',
            f'  --extra-header {api_key_header} "$GATOR_CRUSH_KEY"',
            "",
        ]
        lines += [_model_add_line("gator-anthropic", m, True) for m in claude_models]
        lines.append("")

    if other_models:
        lines += [
            "provider add gator-gateway \\",
            "  --type openai-compat \\",
            f'  --base-url "{unified_url}" \\',
            '  --api-key "$GATOR_CRUSH_KEY" \\',
            f'  --extra-header {api_key_header} "$GATOR_CRUSH_KEY"',
            "",
        ]
        lines += [_model_add_line("gator-gateway", m, False) for m in other_models]
        lines.append("")

    lines += [
        "option default-providers false",
        "option provider-auto-update false",
        "",
        f"model large {default_ref}",
        f"model small {small_ref}",
    ]
    return "\n".join(lines)


def build_crush_env() -> dict[str, str]:
    """CRUSH_GLOBAL_CONFIG + GATOR_CRUSH_KEY for the Crush process, built from
    the active Gator LLM profile — same model split (gator-anthropic /
    gator-gateway) as OpenCode's config injection, adapted to Crush's crushrc
    format (Crush has no env-content equivalent of OPENCODE_CONFIG_CONTENT).

    Writes the crushrc to ~/.gator/crush/crushrc and points CRUSH_GLOBAL_CONFIG
    at that directory, so nothing is written into the user's repo. Raises
    RuntimeError with the same "no API key configured" message the other
    agents use if the profile isn't set up.
    """
    from llm.registry import get_active_profile, available_models

    profile = get_active_profile()
    if not profile.get("api_key"):
        raise RuntimeError("No API key configured — set one up in Gator's Settings first.")

    models = available_models()
    crushrc = _build_crushrc(profile, models)
    _CRUSH_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (_CRUSH_CONFIG_DIR / "crushrc").write_text(crushrc, encoding="utf-8")
    return {
        "CRUSH_GLOBAL_CONFIG": str(_CRUSH_CONFIG_DIR),
        "GATOR_CRUSH_KEY": profile["api_key"],
    }


def _claude_env_from_profile(profile: dict, models: list[str]) -> dict[str, str] | None:
    """Env that points Claude Code at the profile's Anthropic-native gateway
    URL, or None when the profile has no key or no Anthropic endpoint."""
    from llm.gateway import profile_headers

    anthropic_url = (profile.get("anthropic_url") or "").strip().rstrip("/")
    if not profile.get("api_key") or not anthropic_url:
        return None
    # Claude Code appends /v1/messages itself.
    if anthropic_url.endswith("/v1"):
        anthropic_url = anthropic_url[: -len("/v1")]

    claude_models = [m for m in models if "claude" in m.lower()]
    active = profile.get("active_model", "")
    default = active if active in claude_models else (claude_models[0] if claude_models else "")

    def _family(name: str) -> str:
        return next((m for m in claude_models if name in m.lower()), default)

    headers = profile_headers(profile)
    env = {
        "ANTHROPIC_BASE_URL": anthropic_url,
        "ANTHROPIC_API_KEY": profile["api_key"],
        "ANTHROPIC_CUSTOM_HEADERS": "\n".join(f"{k}: {v}" for k, v in headers.items()),
    }
    if default:
        env["ANTHROPIC_MODEL"] = default
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = _family("opus")
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = _family("sonnet")
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = _family("haiku")
        env["ANTHROPIC_SMALL_FAST_MODEL"] = _family("haiku")
    return env


_PI_EXTENSION_DIR = Path.home() / ".gator" / "pi"


def _pi_extension_source(profile: dict, models: list[str]) -> str:
    """A Pi extension registering the gateway as providers, so Pi's own
    ~/.pi/agent configuration stays untouched."""
    import json

    from llm.gateway import normalize_openai_base_url, profile_headers
    from llm.registry import context_window

    headers = {
        name: ("GATOR_GATEWAY_KEY" if name == profile.get("api_key_header") else value)
        for name, value in profile_headers(profile).items()
    }

    def entries(ids: list[str]) -> list[dict]:
        return [
            {"id": m, "name": m, "input": ["text", "image"], "contextWindow": context_window(m), "maxTokens": 16384, "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}}
            for m in ids
        ]

    providers = {}
    anthropic_url = (profile.get("anthropic_url") or "").strip().rstrip("/")
    if anthropic_url.endswith("/v1"):
        anthropic_url = anthropic_url[: -len("/v1")]
    claude = [m for m in models if "claude" in m.lower()]
    if anthropic_url and claude:
        providers["gator-anthropic"] = {
            "name": "AI Gator (Anthropic)",
            "baseUrl": anthropic_url,
            "api": "anthropic-messages",
            "apiKey": "GATOR_GATEWAY_KEY",  # pragma: allowlist secret
            "headers": headers,
            "models": entries(claude),
        }
    others = [m for m in models if "claude" not in m.lower()]
    openai_url = normalize_openai_base_url(profile.get("base_url") or "")
    if openai_url and others:
        providers["gator-gateway"] = {
            "name": "AI Gator",
            "baseUrl": openai_url,
            "api": "openai-completions",
            "apiKey": "GATOR_GATEWAY_KEY",  # pragma: allowlist secret
            "headers": headers,
            "models": entries(others),
        }
    body = "".join(
        f"  pi.registerProvider({json.dumps(name)}, {json.dumps(cfg)});\n"
        for name, cfg in providers.items()
    )
    return f"export default function (pi) {{\n{body}}}\n"


def _pi_binding_from_profile(
    profile: dict, models: list[str]
) -> tuple[tuple[str, ...], dict[str, str]] | None:
    if not profile.get("api_key"):
        return None
    source = _pi_extension_source(profile, models)
    if "registerProvider" not in source:
        return None
    active = profile.get("active_model", "")
    default = active if active in models else models[0]
    provider = "gator-anthropic" if "claude" in default.lower() else "gator-gateway"
    if f'"{provider}"' not in source:
        provider = "gator-gateway" if provider == "gator-anthropic" else "gator-anthropic"
        default = next(
            m for m in models if ("claude" in m.lower()) == (provider == "gator-anthropic")
        )
    _PI_EXTENSION_DIR.mkdir(parents=True, exist_ok=True)
    extension = _PI_EXTENSION_DIR / "gateway.mjs"
    extension.write_text(source, encoding="utf-8")
    args = ("-e", str(extension), "--provider", provider, "--model", default)
    return args, {"GATOR_GATEWAY_KEY": profile["api_key"]}


def gateway_binding(agent: str) -> tuple[tuple[str, ...], dict[str, str]] | None:
    """Extra argv and env that route this agent through the active profile's
    gateway, or None when it can't be bound (the agent then starts on the
    user's own config)."""
    from llm.registry import get_active_profile, available_models

    if agent == "claude":
        env = _claude_env_from_profile(get_active_profile(), available_models())
        return ((), env) if env else None
    if agent == "pi":
        return _pi_binding_from_profile(get_active_profile(), available_models())
    return None


def effective_binding(agent: str) -> tuple[tuple[str, ...], dict[str, str]] | None:
    """gateway_binding, minus agents whose argv would have to cross into WSL
    (Windows paths mean nothing there)."""
    binding = gateway_binding(agent)
    if binding and binding[0] and not find_agent_binary(agent):
        return None
    return binding


def with_wsl_env(command: list[str] | None, env: dict[str, str] | None) -> dict[str, str] | None:
    """Agents launched inside WSL only see Windows variables named in WSLENV."""
    if not env or not command or os.path.basename(command[0]).lower() != "wsl.exe":
        return env
    names = [k for k in env if k != "WSLENV"]
    existing = os.environ.get("WSLENV", "")
    return {**env, "WSLENV": ":".join(filter(None, [existing, *names]))}
