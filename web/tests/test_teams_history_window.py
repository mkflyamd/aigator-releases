"""Teams chat history & search must not be capped at ~2 days — Issue #66.

Two backend defects are in scope here (the list-view "load older" wiring and the
in-UI window indicator are frontend and need the running app, so they are out of
scope for these tests):

1. The AI-agent tool `_tool_read_teams_chats` defaulted to `hours=24` — far too
   narrow for "find that thread from last week" questions. The default must cover
   at least 30 days.
2. The Teams search endpoint must not be bounded by the same narrow window as the
   chat list. It must fetch a substantially wider set of chats than the list-view
   default before filtering, so older conversations are searchable.
"""
import inspect
import pathlib

TEAMS_SRC = (pathlib.Path(__file__).parent.parent / "routes" / "teams.py").read_text(encoding="utf-8")


def test_agent_tool_default_window_covers_at_least_30_days():
    from skills.teams.tools import _tool_read_teams_chats
    default_hours = inspect.signature(_tool_read_teams_chats).parameters["hours"].default
    assert default_hours >= 720, (
        f"agent tool default window is {default_hours}h — must be >= 720h (30 days) (#66)"
    )


def test_llm_facing_default_window_covers_at_least_30_days():
    # The signature default rarely fires — the LLM emits the schema's `default`, and
    # the pinned-item auto-invocation uses DIRECT_INTENTS. Both must be wide too (#66).
    from skills.teams import tools
    schema_default = next(
        td for td in tools.TOOL_DEFS if td["name"] == "read_teams_chats"
    )["input_schema"]["properties"]["hours"]["default"]
    assert schema_default >= 720, (
        f"read_teams_chats schema default is {schema_default}h — LLM will use this; "
        f"must be >= 720h (#66)"
    )
    intent = next(d for d in tools.DIRECT_INTENTS if d["tool"] == "read_teams_chats")
    assert intent["args"]["hours"] >= 720, (
        f"DIRECT_INTENTS hours is {intent['args']['hours']} — pinned-item auto-invoke "
        f"must use the wide window too (#66)"
    )


def test_agent_tool_fetch_limit_not_capped_below_window():
    # A wide time window is theater if the chat fetch is capped low — chats beyond the
    # cap are never seen by the `since` filter. The list fetch must be >= 200 (#66).
    import re
    src = (pathlib.Path(__file__).parent.parent / "skills" / "teams" / "tools.py").read_text(encoding="utf-8")
    start = src.find("def _tool_read_teams_chats")
    body = src[start:start + 3000]
    limits = [int(n) for n in re.findall(r"list_chats\([^)]*limit=(\d+)", body)]
    assert limits, "_tool_read_teams_chats must call list_chats with an explicit limit"
    assert max(limits) >= 200, (
        f"agent tool list_chats limit caps at {max(limits)} — too low to cover a 30-day "
        f"window; raise to >= 200 (#66)"
    )


def test_search_fetches_wider_window_than_list_default():
    # The list view defaults to top=50; search must fetch a much larger set before
    # filtering so it is not bounded by the same ~2-day window (#66).
    start = TEAMS_SRC.find("def tp_teams_search")
    assert start != -1, "tp_teams_search must exist"
    body = TEAMS_SRC[start:start + 1200]
    import re
    m = re.search(r"list_chats\([^)]*limit=(\d+)", body)
    assert m, "tp_teams_search must call list_chats with an explicit limit"
    search_limit = int(m.group(1))
    assert search_limit >= 1000, (
        f"search fetch limit is {search_limit} — too narrow; must be >= 1000 so older "
        f"chats are searchable, decoupled from the list-view window (#66)"
    )
