"""Kill switch: turn an installed marketplace skill or plugin bundle off and back on."""
from __future__ import annotations

import logging

from marketplace import installer, loader, state
from marketplace.commands import deregister_plugin_commands, register_plugin_commands

logger = logging.getLogger(__name__)


def _step(label: str, fn, *args) -> None:
    try:
        fn(*args)
    except Exception:
        logger.warning("kill switch: %s failed", label, exc_info=True)


def _find(skill_id: str):
    entry = state.get_entry(skill_id)
    if entry is None or entry.get("id") != skill_id:
        return None, {"ok": False, "error": f"skill not found: {skill_id}"}
    return entry, None


def _refresh_prompts() -> None:
    import shared

    shared.load_installed_skill_prompts()


def disable(skill_id: str) -> dict:
    entry, error = _find(skill_id)
    if error:
        return error
    state.set_disabled(skill_id, True)
    inner_ids = entry.get("skill_ids")
    for sid in [skill_id, *(inner_ids or [])]:
        _step(f"unload tools of {sid}", loader.unload_skill_tools, sid)
    if inner_ids is not None:
        _step(f"stop MCP servers of {skill_id}", installer._teardown_plugin_mcp, skill_id)
        _step(f"remove commands of {skill_id}", deregister_plugin_commands, entry.get("command_ids") or [])
    _step("refresh skill prompts", _refresh_prompts)
    return {"ok": True}


def _enable_tools(skill_id: str, entry: dict, skill_dir) -> None:
    if entry.get("skill_ids") is not None:
        installer._register_plugin_mcp_servers(skill_id, skill_dir)
        register_plugin_commands(skill_id, skill_dir)
    elif skill_dir.exists():
        result = loader.load_skill_tools(skill_id, skill_dir, entry.get("tier") or "Community")
        if not result.get("ok"):
            logger.warning("kill switch: tools of %s did not reload: %s", skill_id, result.get("error"))
    else:
        logger.warning("kill switch: skill folder of %s not found at %s; its tools were not reloaded",
                       skill_id, skill_dir)


def enable(skill_id: str) -> dict:
    entry, error = _find(skill_id)
    if error:
        return error
    if not entry.get("disabled"):
        return {"ok": True}  # already enabled: restoring again would reset live MCP connections
    state.set_disabled(skill_id, False)
    _step("refresh skill prompts", _refresh_prompts)
    _step(f"restore {skill_id}", _enable_tools, skill_id, entry, state.skill_dir_for(entry))
    return {"ok": True}
