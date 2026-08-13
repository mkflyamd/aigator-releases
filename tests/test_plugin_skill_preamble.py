"""Tests for the Gator-plugin-context preamble injection (Option 1).

The user-facing half of the fix: when a claude-plugins-official plugin's
SKILL.md is injected into the system prompt, it must be prefixed ONCE with
_GATOR_PLUGIN_SKILL_PREAMBLE (so the model knows it's in AI Gator, not the
Claude Code CLI). All four injection sites (explicit / inferred / mid-stream
auto-activate in routes.chat, plus the background worker in app.py) route
through the single _append_skill_prompt helper, so testing that helper covers
the invariant for every site: "if a plugin skill's body is in `system`, the
preamble is too — exactly once."
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "web"))

from unittest.mock import patch


def _chat():
    import importlib

    return importlib.import_module("routes.chat")


def test_native_skill_gets_no_preamble():
    chat = _chat()
    with (
        patch.dict("shared.SKILL_PROMPTS", {"email": "EMAIL GUIDE"}, clear=False),
        patch.object(chat, "_is_plugin_bundled_skill", return_value=False),
    ):
        system, done = chat._append_skill_prompt("BASE", "email", False)

    assert "EMAIL GUIDE" in system
    assert chat._GATOR_PLUGIN_SKILL_PREAMBLE not in system
    assert done is False


def test_plugin_skill_gets_preamble_once_and_body():
    chat = _chat()
    with (
        patch.dict(
            "shared.SKILL_PROMPTS", {"datadog__skills-ddsetup": "DD GUIDE"}, clear=False
        ),
        patch.object(chat, "_is_plugin_bundled_skill", return_value=True),
    ):
        system, done = chat._append_skill_prompt(
            "BASE", "datadog__skills-ddsetup", False
        )

    assert "DD GUIDE" in system
    assert system.count(chat._GATOR_PLUGIN_SKILL_PREAMBLE) == 1
    assert done is True
    # Preamble precedes the plugin body.
    assert system.index(chat._GATOR_PLUGIN_SKILL_PREAMBLE) < system.index("DD GUIDE")


def test_two_plugin_skills_inject_preamble_exactly_once():
    chat = _chat()
    prompts = {"datadog__skills-ddsetup": "DD1", "datadog__skills-ddconfig": "DD2"}
    with (
        patch.dict("shared.SKILL_PROMPTS", prompts, clear=False),
        patch.object(chat, "_is_plugin_bundled_skill", return_value=True),
    ):
        system, done = chat._append_skill_prompt(
            "BASE", "datadog__skills-ddsetup", False
        )
        system, done = chat._append_skill_prompt(
            system, "datadog__skills-ddconfig", done
        )

    assert "DD1" in system and "DD2" in system
    assert system.count(chat._GATOR_PLUGIN_SKILL_PREAMBLE) == 1
    assert done is True


def test_native_then_plugin_injects_preamble_before_plugin_body():
    chat = _chat()
    prompts = {"email": "EMAIL GUIDE", "datadog__skills-ddsetup": "DD GUIDE"}

    def _is_plugin(sid):
        return "__" in sid

    with (
        patch.dict("shared.SKILL_PROMPTS", prompts, clear=False),
        patch.object(chat, "_is_plugin_bundled_skill", side_effect=_is_plugin),
    ):
        system, done = chat._append_skill_prompt("BASE", "email", False)
        assert (
            chat._GATOR_PLUGIN_SKILL_PREAMBLE not in system
        )  # native first: still none
        system, done = chat._append_skill_prompt(
            system, "datadog__skills-ddsetup", done
        )

    assert system.count(chat._GATOR_PLUGIN_SKILL_PREAMBLE) == 1
    assert done is True
    assert system.index(chat._GATOR_PLUGIN_SKILL_PREAMBLE) < system.index("DD GUIDE")
    # Native body injected before the preamble (it came first, pre-plugin).
    assert system.index("EMAIL GUIDE") < system.index(chat._GATOR_PLUGIN_SKILL_PREAMBLE)


def test_preamble_not_reinjected_when_flag_already_done():
    chat = _chat()
    with (
        patch.dict(
            "shared.SKILL_PROMPTS", {"datadog__skills-ddsetup": "DD GUIDE"}, clear=False
        ),
        patch.object(chat, "_is_plugin_bundled_skill", return_value=True),
    ):
        # Simulate the mid-stream site seeding done=True because _current_system
        # already carries the preamble from an earlier pass this request.
        system, done = chat._append_skill_prompt(
            "BASE", "datadog__skills-ddsetup", True
        )

    assert "DD GUIDE" in system
    assert chat._GATOR_PLUGIN_SKILL_PREAMBLE not in system
    assert done is True
