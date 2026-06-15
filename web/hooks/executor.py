"""Fire hook shell commands for a given event. Exit code 0 = allow, non-zero = block."""

import json
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Hook commands are author-supplied (untrusted). Strip gateway credentials
# from the subprocess env so a malicious plugin hook can't exfiltrate them.
# See CLAUDE.md for gateway compliance details.
_BLOCKED_ENV_VARS = frozenset({"ANTHROPIC_API_KEY", "GATEWAY_USER_ID", "LLM_GATEWAY_URL"})


def _safe_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in _BLOCKED_ENV_VARS}


def fire_event(event_name: str, skill_dir: Path) -> dict:
    """Fire all hooks matching event_name in skill_dir/hooks.json.

    Returns {"blocked": bool, "reason": str}.
    blocked=True if any hook exits with a non-zero code.

    Security: hook commands are author-supplied (untrusted). They execute on the
    local machine with the user's shell. We enforce a 30s timeout and capture
    output so a stuck/runaway hook cannot block the app indefinitely.
    """
    hooks_file = skill_dir / "hooks.json"
    if not hooks_file.exists():
        return {"blocked": False, "reason": ""}

    try:
        config = json.loads(hooks_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Malformed hooks.json in %s: %s", skill_dir, exc)
        return {"blocked": False, "reason": ""}

    for hook in config.get("hooks", []):
        if hook.get("event") != event_name:
            continue
        command = hook.get("command", "")
        if not command:
            continue
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                env=_safe_env(),
            )
            if proc.returncode != 0:
                reason = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
                logger.info("Hook blocked event %s: %s", event_name, reason)
                return {"blocked": True, "reason": reason}
        except subprocess.TimeoutExpired:
            logger.warning("Hook timed out for event %s in %s", event_name, skill_dir)
            return {"blocked": True, "reason": "hook timed out"}
        except Exception as exc:
            # Fail closed: if we can't determine whether the hook would allow,
            # treat as a block. For send-style events (email/Teams/Slack) this
            # is the safe default — better to surface an error than silently send.
            logger.warning("Hook error for event %s: %s", event_name, exc)
            return {"blocked": True, "reason": f"hook error: {exc}"}

    return {"blocked": False, "reason": ""}


def fire_all_skill_hooks(event_name: str) -> dict:
    """Fire event across all installed plugin skill directories.

    Iterates the installed-skills index — NOT `INSTALLED_TOOL_MODULES` —
    because a plugin can ship `hooks.json` with no `tools.py` (MCP-only or
    CLI-shim plugin) and would otherwise be invisible to the hook gate,
    silently bypassing a compliance-enforcement plugin.

    Returns {"blocked": True, "reason": ...} if any hook blocks, else
    {"blocked": False, "reason": ""}.
    """
    try:
        from config import PLUGINS_DIR, INSTALLED_SKILLS_DIR
        from marketplace.installer import load_installed
    except ImportError as exc:
        # Surface real import bugs in the log instead of silently bypassing
        # every hook — a typo in config.py shouldn't disarm the gate.
        logger.error("fire_all_skill_hooks: import failure (hooks not fired): %s", exc)
        return {"blocked": False, "reason": ""}

    for entry in load_installed():
        skill_id = entry.get("id")
        if not skill_id:
            continue
        source = entry.get("source", "")
        version = entry.get("version", "")
        # NOTE: fire_event appends `hooks.json` to skill_dir, so we pass the
        # skill ROOT here — adding a `/hooks` segment would yield .../hooks/hooks.json
        # and silently miss every file.
        if source and version:
            skill_dir = PLUGINS_DIR / "cache" / source / skill_id / version
        else:
            skill_dir = INSTALLED_SKILLS_DIR / skill_id
        result = fire_event(event_name, skill_dir)
        if result["blocked"]:
            return result

    return {"blocked": False, "reason": ""}
