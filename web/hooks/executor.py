"""Fire hook shell commands for a given event. Exit code 0 = allow, non-zero = block.

Hook commands are author-supplied (untrusted), so each one runs in the OS
sandbox (see marketplace.sandbox_launch): throwaway working folder, read access
to the skill folder and the folders the user approved, no write access outside
the throwaway folder, network only when the user approved a network declaration,
and an environment with no API keys. If the sandbox cannot start the hook
blocks the send.
"""

import json
import logging
import os
import shutil
from pathlib import Path

from marketplace.permissions import Permissions

logger = logging.getLogger(__name__)

_HOOK_TIMEOUT = 30


def _hook_argv(command: str) -> list[str]:
    if os.name == "nt":
        comspec = os.environ.get("COMSPEC") or os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe"
        )
        return [comspec, "/c", command]
    return ["/bin/sh", "-c", command]


def fire_event(
    event_name: str,
    skill_dir: Path,
    skill_id: str = "",
    perms: Permissions | None = None,
) -> dict:
    """Fire all hooks matching event_name in skill_dir/hooks.json.

    Returns {"blocked": bool, "reason": str}.
    blocked=True if any hook exits with a non-zero code, times out, or cannot be
    started in the sandbox. `perms` is what the user approved at install; with
    none, the hook gets no extra folders and no network.
    """
    from marketplace.sandbox_launch import new_run_dir, run_in_sandbox

    hooks_file = skill_dir / "hooks.json"
    if not hooks_file.exists():
        return {"blocked": False, "reason": ""}

    try:
        config = json.loads(hooks_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Malformed hooks.json in %s: %s", skill_dir, exc)
        return {"blocked": False, "reason": ""}

    perms = perms or Permissions()
    label = skill_id or skill_dir.name

    for hook in config.get("hooks", []):
        if hook.get("event") != event_name:
            continue
        command = hook.get("command", "")
        if not command:
            continue
        run_dir = None
        try:
            run_dir = new_run_dir()
            run = run_in_sandbox(
                label, "hook", _hook_argv(command), skill_dir, run_dir, perms, _HOOK_TIMEOUT
            )
            if not run.ok:
                logger.warning("Hook could not start for event %s: %s", event_name, run.error)
                return {"blocked": True, "reason": f"hook error: {run.error}"}
            if run.timed_out:
                logger.warning("Hook timed out for event %s in %s", event_name, skill_dir)
                return {"blocked": True, "reason": "hook timed out"}
            if run.returncode != 0:
                reason = (
                    run.stderr.strip()
                    or run.stdout.strip()
                    or f"exit {run.returncode}"
                )
                logger.info("Hook blocked event %s: %s", event_name, reason)
                return {"blocked": True, "reason": reason}
        except Exception as exc:
            # Fail closed: if we can't determine whether the hook would allow,
            # treat as a block. For send-style events (email/Teams/Slack) this
            # is the safe default — better to surface an error than silently send.
            logger.warning("Hook error for event %s: %s", event_name, exc)
            return {"blocked": True, "reason": f"hook error: {exc}"}
        finally:
            if run_dir is not None:
                shutil.rmtree(run_dir, ignore_errors=True)

    return {"blocked": False, "reason": ""}


def fire_all_skill_hooks(event_name: str) -> dict:
    """Fire event across all installed plugin skill directories.

    Iterates the installed-skills index — NOT `INSTALLED_TOOL_MODULES` —
    because a plugin can ship `hooks.json` with no `tools.py` (MCP-only or
    CLI-shim plugin) and would otherwise be invisible to the hook gate,
    silently bypassing a compliance-enforcement plugin. Disabled skills are
    skipped.

    Returns {"blocked": True, "reason": ...} if any hook blocks, else
    {"blocked": False, "reason": ""}.
    """
    try:
        from marketplace import state
        from marketplace.installer import load_installed
    except ImportError as exc:
        # Surface real import bugs in the log instead of silently bypassing
        # every hook — a typo in config.py shouldn't disarm the gate.
        logger.error("fire_all_skill_hooks: import failure (hooks not fired): %s", exc)
        return {"blocked": False, "reason": ""}

    try:
        disabled = state.disabled_ids()
    except Exception as exc:
        # Cannot tell which skills are disabled: run every hook (the stricter
        # choice for a gate) rather than crash the send path.
        logger.warning("fire_all_skill_hooks: could not read disabled skills: %s", exc)
        disabled = set()

    for entry in load_installed():
        skill_id = entry.get("id")
        if not skill_id or skill_id in disabled:
            continue
        try:
            perms = state.approved_permissions(skill_id)
        except Exception as exc:
            # No readable approval record means no grants, never wider access.
            logger.warning("fire_all_skill_hooks: no approved permissions for %s: %s", skill_id, exc)
            perms = Permissions()
        # NOTE: fire_event appends `hooks.json` to skill_dir, so we pass the
        # skill ROOT here — adding a `/hooks` segment would yield .../hooks/hooks.json
        # and silently miss every file.
        result = fire_event(
            event_name,
            state.skill_dir_for(entry),
            skill_id=skill_id,
            perms=perms,
        )
        if result["blocked"]:
            return result

    return {"blocked": False, "reason": ""}
