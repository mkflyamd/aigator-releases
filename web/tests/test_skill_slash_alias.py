"""/plugin:capability slash commands must alias-resolve the skill id — Issue #40.

A skill invoked via the `/outlook:...` slash command set active_skill="outlook"
verbatim. The user-facing name "outlook" maps to internal skill id "email"
(_SKILL_NAME_ALIASES), but that resolution was only applied in the auto-activate
fallback path — not the explicit slash-command path. So `/outlook:...` produced an
active_skill present in neither SKILL_PROMPTS nor SKILL_TOOLS_MAP: the skill looked
loaded but exposed no tools. Both paths must share one alias-resolution helper.
"""
import pathlib

import app  # noqa: F401 — importing triggers skill-module load (populates SKILL_TOOLS_MAP)
import shared
from routes.chat import _filter_tools, _resolve_skill_id

CHAT_SRC = (pathlib.Path(__file__).parent.parent / "routes" / "chat.py").read_text(encoding="utf-8")


def test_resolve_alias_outlook_to_email():
    assert _resolve_skill_id("outlook") == "email"
    assert _resolve_skill_id("OUTLOOK") == "email", "resolution must be case-insensitive"


def test_resolve_passthrough_unknown():
    assert _resolve_skill_id("git") == "git"


def test_alias_resolution_exposes_email_tools():
    email_tools = shared.SKILL_TOOLS_MAP.get("email", set())
    assert email_tools, "email skill tools should be registered at startup"
    # The raw user-facing name does NOT map to the email toolset (the bug).
    raw = {t["name"] for t in _filter_tools("outlook", False)}
    assert not (email_tools & raw), "raw 'outlook' should expose no email tools (bug repro)"
    # Alias-resolving it to the internal id DOES (the fix).
    resolved = {t["name"] for t in _filter_tools(_resolve_skill_id("outlook"), False)}
    assert email_tools & resolved, "alias-resolved outlook must expose email tools (#40)"


def test_slash_command_path_uses_resolver():
    # The slash-command block must alias-resolve the plugin name and use the
    # resolved id for both the registry check and active_skill — not assign the
    # raw name verbatim.
    assert '_resolved_plugin = _resolve_skill_id(slash_cmd["plugin"])' in CHAT_SRC, \
        "slash-command plugin name must be alias-resolved (#40)"
    assert '"active_skill": _resolved_plugin' in CHAT_SRC, \
        "active_skill must use the resolved id (#40)"
    assert "if _resolved_plugin not in shared.SKILL_PROMPTS" in CHAT_SRC, \
        "registry check must use the resolved id so aliases don't log false warnings (#40)"
