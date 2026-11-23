import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest

import shared
from mcp.manager import _register, _unregister
from tool_pipeline import (
    _GOOGLE_SERVICE_TOOLS,
    GOOGLE_UMBRELLA_ID,
    expand_google_umbrella,
    google_groups_for_message,
)

_ALL = {f"g-{n}" for n in ("gmail", "drive", "calendar", "docs", "sheets", "slides", "forms", "tasks", "contacts", "chat", "search", "script")}


def test_groups_follow_message_intent():
    assert google_groups_for_message("what is in my gmail inbox") == ["g-gmail"]
    got = google_groups_for_message("put this on my calendar and email it")
    assert "g-calendar" in got and "g-gmail" in got
    assert "g-sheets" in google_groups_for_message("update the spreadsheet")


def test_groups_default_to_gmail_calendar_drive():
    assert google_groups_for_message("hello there") == ["g-gmail", "g-calendar", "g-drive"]
    assert google_groups_for_message("") == ["g-gmail", "g-calendar", "g-drive"]


def test_expand_replaces_only_the_umbrella():
    out = expand_google_umbrella([GOOGLE_UMBRELLA_ID, "jira"], "check my calendar", _ALL)
    assert out == ["g-calendar", "jira"]


def test_expand_dedupes_and_keeps_explicit_groups():
    out = expand_google_umbrella(["g-gmail", GOOGLE_UMBRELLA_ID], "read my email", _ALL)
    assert out == ["g-gmail"]


def test_expand_skips_groups_that_are_not_available():
    assert expand_google_umbrella([GOOGLE_UMBRELLA_ID], "gmail", {"g-calendar"}) == []


def _umbrella_conn(fillers=17):
    names = sorted(set().union(*_GOOGLE_SERVICE_TOOLS.values()) | {"start_google_auth"})
    names += [f"filler_tool_{i}" for i in range(fillers)]
    return {
        "id": GOOGLE_UMBRELLA_ID,
        "name": "Google Workspace",
        "cached_tools": [{"name": n, "input_schema": {"type": "object"}} for n in names],
    }


@pytest.fixture
def umbrella(monkeypatch):
    conn = _umbrella_conn()
    monkeypatch.setattr(shared, "_ALWAYS_ON_TOOLS", set())
    _unregister(conn["id"])
    _register(conn)
    yield conn
    _unregister(conn["id"])


def test_fixture_reproduces_the_138_tool_umbrella(umbrella):
    assert len(shared.SKILL_TOOLS_MAP[GOOGLE_UMBRELLA_ID]) == 138


def test_filter_tools_with_umbrella_stays_under_the_model_limit(umbrella):
    from routes.chat import _filter_tools

    selected = _filter_tools(None, False, [GOOGLE_UMBRELLA_ID], message="what is in my gmail inbox")
    names = {t["name"] for t in selected}
    assert len(names) <= 128
    assert names == set(shared.SKILL_TOOLS_MAP["g-gmail"])


def test_filter_tools_with_umbrella_as_active_skill(umbrella):
    from routes.chat import _filter_tools

    selected = _filter_tools(GOOGLE_UMBRELLA_ID, False, [], message="")
    names = {t["name"] for t in selected}
    expected = set().union(*(shared.SKILL_TOOLS_MAP[g] for g in ("g-gmail", "g-calendar", "g-drive")))
    assert names == expected and len(names) <= 128


def test_catalog_hides_the_umbrella(umbrella, monkeypatch):
    import mcp.manager as M
    from routes.chat import _mcp_catalog

    other = {"id": "mcp-other", "name": "Other", "enabled": True, "cached_tools": [{"name": "t"}]}
    monkeypatch.setattr(M, "_load_connections", lambda: [dict(umbrella, enabled=True), other])
    catalog = _mcp_catalog()
    assert GOOGLE_UMBRELLA_ID not in catalog
    assert "mcp-other" in catalog


def test_overflow_message_is_actionable():
    from routes.chat import _tool_budget_overflow_message

    msg = _tool_budget_overflow_message(150, 128, 160)
    assert "150" in msg and "128" in msg and "160" in msg
    assert "Settings → Tools" in msg
