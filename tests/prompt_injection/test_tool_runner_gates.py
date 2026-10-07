import asyncio
from types import SimpleNamespace

import pytest

import app  # noqa: F401  (builds the tool registry)
import agent_loop
import data_sources as ds
from agent_loop import _make_tool_runner
from browser_agent import resolve_browser_confirm


@pytest.fixture(autouse=True)
def _fresh():
    ds._reset()
    yield
    ds._reset()


def _tc(name, inputs=None, call_id="c1"):
    return SimpleNamespace(id=call_id, name=name, inputs=inputs or {})


def _runner(calls, *, context_id="tab-a", offered=None, result=None):
    async def execute_tool(name, inputs):
        calls.append(name)
        return dict(result) if result is not None else {"ok": True}

    run, _, _ = _make_tool_runner(
        execute_tool, frozenset(), {}, lambda n, r: None, "safe",
        context_id=context_id, offered_names=offered,
    )
    return run


async def _answer(queue, allow, cards=None):
    while True:
        evt = await asyncio.wait_for(queue.get(), 5)
        if evt["kind"] == "browser_confirm":
            if cards is not None:
                cards.append(evt)
            resolve_browser_confirm(evt["confirm_id"], allow)
            return


async def test_a_tool_that_was_not_offered_is_rejected():
    calls = []
    run = _runner(calls, offered=frozenset({"read_email"}))
    res = await run(_tc("search_email"), asyncio.Queue())
    assert res["error"] == "tool_not_offered"
    assert calls == []


async def test_first_use_of_a_source_asks_then_remembers_for_the_tab():
    calls, cards, q = [], [], asyncio.Queue()
    run = _runner(calls)
    res, _ = await asyncio.gather(run(_tc("search_email"), q), _answer(q, True, cards))
    assert res.get("ok") is True and calls == ["search_email"]
    assert cards[0]["title"] == "Allow access to Outlook mail?"
    assert cards[0]["allow_label"] == "Allow for this tab" and cards[0]["deny_label"] == "Deny"
    assert ds.is_allowed("tab-a", "data:Outlook mail")
    await asyncio.wait_for(run(_tc("read_email", call_id="c2"), asyncio.Queue()), 5)  # no card, would hang
    assert calls == ["search_email", "read_email"]


async def test_deny_returns_an_error_and_does_not_run_the_tool():
    calls, q = [], asyncio.Queue()
    run = _runner(calls)
    res, _ = await asyncio.gather(run(_tc("jira_search"), q), _answer(q, False))
    assert res["error"] == "data_source_denied" and "Jira" in res["source"]
    assert "do not retry" in res["hint"].lower()
    assert calls == []
    assert not ds.is_allowed("tab-a", "data:Jira")


async def test_a_denied_source_is_not_asked_again_straight_away():
    calls, q = [], asyncio.Queue()
    run = _runner(calls)
    await asyncio.gather(run(_tc("jira_search"), q), _answer(q, False))
    again = await asyncio.wait_for(run(_tc("jira_get_issue", call_id="c2"), asyncio.Queue()), 5)
    assert again["error"] == "data_source_denied"


async def test_another_tab_must_ask_again():
    ds.allow("tab-a", "data:Slack")
    calls, q = [], asyncio.Queue()
    run = _runner(calls, context_id="tab-b")
    res, _ = await asyncio.gather(run(_tc("slack_search_users"), q), _answer(q, True))
    assert res.get("ok") is True
    assert ds.is_allowed("tab-b", "data:Slack")


async def test_parallel_calls_to_one_new_source_share_one_card():
    calls, cards, q = [], [], asyncio.Queue()
    run = _runner(calls)
    await asyncio.gather(
        run(_tc("search_email", call_id="a"), q),
        run(_tc("read_email", call_id="b"), q),
        _answer(q, True, cards),
    )
    assert len(cards) == 1 and sorted(calls) == ["read_email", "search_email"]


async def test_an_unanswered_card_expires_as_a_denial(monkeypatch):
    monkeypatch.setattr(agent_loop, "_CONFIRM_TIMEOUT_S", 0.05)
    calls = []
    res = await _runner(calls)(_tc("search_email"), asyncio.Queue())
    assert res["error"] == "data_source_denied" and calls == []


async def test_no_card_without_a_tab_or_for_tools_with_no_source():
    calls = []
    res = await asyncio.wait_for(_runner(calls, context_id=None)(_tc("search_email"), asyncio.Queue()), 5)
    assert res.get("ok") is True
    res = await asyncio.wait_for(_runner(calls)(_tc("create_docx"), asyncio.Queue()), 5)
    assert res.get("ok") is True


async def test_a_new_website_host_asks_and_the_card_names_the_host():
    calls, cards, q = [], [], asyncio.Queue()
    run = _runner(calls)
    res, _ = await asyncio.gather(
        run(_tc("fetch_webpage", {"url": "https://docs.example.com/a"}), q), _answer(q, True, cards)
    )
    assert "docs.example.com" in cards[0]["title"] and res.get("ok") is True
    # a second page on the same host needs no card
    await asyncio.wait_for(run(_tc("fetch_webpage", {"url": "https://docs.example.com/b"}, "c2"), asyncio.Queue()), 5)


def test_offered_names_reads_both_tool_shapes():
    tools = [{"name": "a"}, {"type": "function", "function": {"name": "b"}}, "junk"]
    assert agent_loop._offered_tool_names(tools) == frozenset({"a", "b"})
    assert agent_loop._offered_tool_names([]) == frozenset()


def test_both_loops_hand_the_runner_the_tab_and_the_offered_tools():
    import inspect
    src = inspect.getsource(agent_loop)
    assert src.count('("confirm_id", "action", "title", "allow_label", "deny_label")') == 2
    assert src.count("context_id=context_id, offered_names=_offered_tool_names(normalized_tools)") == 2
