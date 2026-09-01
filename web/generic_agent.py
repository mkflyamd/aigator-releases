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

import shutil
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

# A bare shell in the project directory - the maximally-flexible fallback for
# a tool not in SUPPORTED_AGENTS (or no tool at all), rather than maintaining
# an ever-growing fixed list. Not in SUPPORTED_AGENTS since it needs no
# binary resolution at all - it's just create_pty_session(command=None) with
# cwd set to the project, identical to what the general terminal.js panel
# already spawns, just scoped to a specific repo instead of Gator's own cwd.
TERMINAL_AGENT = "terminal"

# Bare-process OpenCode test (see module docstring). Not in SUPPORTED_AGENTS
# since its binary is bundled (found via instance_manager.find_bundled_
# opencode), not PATH-resolved, and it needs Gator's gateway config injected
# via env — build_opencode_bare_command/_env below handle both.
OPENCODE_BARE_AGENT = "opencode-bare"


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
    return shutil.which(argv[0])


def build_command(agent: str) -> list[str] | None:
    """Full argv to spawn for this agent, with the resolved absolute binary
    path in place of the bare name (matches OpenCode's own build_opencode_
    command pattern of never relying on child-process PATH resolution)."""
    argv = SUPPORTED_AGENTS.get(agent)
    if not argv:
        return None
    resolved = find_agent_binary(agent)
    if not resolved:
        return None
    return [resolved, *argv[1:]]


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


def build_opencode_bare_command(repo_path: str) -> list[str] | None:
    """argv for a single bare `opencode` process rooted at repo_path — no
    `serve`, no `attach`. None if the bundled binary isn't found (mirrors
    build_command's contract for the route layer's "not installed" error).

    No --session resume: a lost/restarted PTY just starts a fresh OpenCode
    session, same tradeoff _active_sessions already documents for every other
    agent here — this is a connectivity test, not a resume-parity feature.
    """
    from skills.opencode_agent.binary import find_bundled_opencode
    resolved = find_bundled_opencode()
    if not resolved:
        return None
    return [str(resolved), repo_path]


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
                           "modalities": {"input": ["text", "image"], "output": ["text"]}}
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
