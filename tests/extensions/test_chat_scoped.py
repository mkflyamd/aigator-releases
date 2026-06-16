"""Tests for ChatRequest.system_prompt_suffix and ChatRequest.scoped_skill extensions."""
import sys
from pathlib import Path

# Ensure web/ is on the path (conftest adds it, but keep explicit for clarity)
_WEB = Path(__file__).parent.parent.parent / "web"
if str(_WEB) not in sys.path:
    sys.path.insert(0, str(_WEB))

from unittest.mock import patch, MagicMock
import shared

from routes.chat import ChatRequest, _filter_tools


def test_chat_request_accepts_system_prompt_suffix():
    req = ChatRequest(message="hi", system_prompt_suffix="EXTRA RULES")
    assert req.system_prompt_suffix == "EXTRA RULES"


def test_chat_request_accepts_scoped_skill():
    req = ChatRequest(message="hi", scoped_skill="_extension_setup")
    assert req.scoped_skill == "_extension_setup"


def test_chat_request_defaults_remain_backwards_compatible():
    req = ChatRequest(message="hi")
    assert req.system_prompt_suffix is None
    assert req.scoped_skill is None


def test_filter_tools_includes_scoped_skill_tools():
    """scoped_skill tools should appear in _filter_tools output when passed via active_skills."""
    # _extension_setup is registered at shared import (Task 4)
    if "_extension_setup" not in shared.SKILL_TOOLS_MAP:
        import pytest
        pytest.skip("_extension_setup not registered in SKILL_TOOLS_MAP — Task 4 not yet applied")

    tools = _filter_tools(
        active_skill="",
        has_images=False,
        active_skills=["_extension_setup"],
        unapproved_deps=None,
    )
    tool_names = {t["name"] for t in tools}
    # All tools registered for _extension_setup should be present
    expected = shared.SKILL_TOOLS_MAP["_extension_setup"]
    assert expected.issubset(tool_names), (
        f"Missing tools from _extension_setup: {expected - tool_names}"
    )
