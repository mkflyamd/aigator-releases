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


async def test_an_expired_card_tells_the_screen_to_drop_it(monkeypatch):
    monkeypatch.setattr(agent_loop, "_CONFIRM_TIMEOUT_S", 0.05)
    q = asyncio.Queue()
    await _runner([])(_tc("search_email"), q)
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    card = next(e for e in events if e["kind"] == "browser_confirm")
    expired = [e for e in events if e["kind"] == "browser_confirm_expired"]
    assert [e["confirm_id"] for e in expired] == [card["confirm_id"]]


async def test_an_answered_card_is_not_reported_expired():
    q = asyncio.Queue()
    await asyncio.gather(_runner([])(_tc("search_email"), q), _answer(q, True))
    assert all(e["kind"] != "browser_confirm_expired" for e in list(q._queue))


def test_resolving_an_unknown_confirm_id_reports_it_was_not_pending():
    assert resolve_browser_confirm("no-such-id", True) is False


async def test_the_confirm_routes_say_when_the_card_has_expired():
    from routes.tasks import browser_confirm_allow, browser_confirm_cancel

    assert await browser_confirm_allow("no-such-id") == {"ok": False, "expired": True}
    assert await browser_confirm_cancel("no-such-id") == {"ok": False, "expired": True}


async def test_the_confirm_route_still_answers_a_pending_card():
    from routes.tasks import browser_confirm_allow

    calls, q = [], asyncio.Queue()
    run = _runner(calls)

    async def click():
        while True:
            evt = await asyncio.wait_for(q.get(), 5)
            if evt["kind"] == "browser_confirm":
                return await browser_confirm_allow(evt["confirm_id"])

    res, reply = await asyncio.gather(run(_tc("search_email"), q), click())
    assert reply == {"ok": True} and res.get("ok") is True


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
    assert "https://docs.example.com/a" in cards[0]["action"]
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


# ── schedule_task needs a per-call card, and is refused in unattended runs ────

_SCHED = {
    "name": "Inbox sweep", "prompt": "x" * 400, "trigger_type": "date",
    "run_date": "2026-10-08T09:00:00", "skills": ["email", "calendar"],
}


async def test_schedule_task_shows_a_card_with_the_job_details_before_creating_anything():
    calls, cards, q = [], [], asyncio.Queue()
    run = _runner(calls)

    async def _check_then_allow():
        while True:
            evt = await asyncio.wait_for(q.get(), 5)
            if evt["kind"] == "browser_confirm":
                cards.append(evt)
                assert calls == []  # nothing created while the card is open
                resolve_browser_confirm(evt["confirm_id"], True)
                return

    res, _ = await asyncio.gather(run(_tc("schedule_task", _SCHED), q), _check_then_allow())
    assert res.get("ok") is True and calls == ["schedule_task"]
    card = cards[0]
    assert card["title"] == "Allow AI Gator to schedule a task?"
    assert card["allow_label"] == "Allow" and card["deny_label"] == "Deny"
    for part in ("Inbox sweep", "date", "2026-10-08T09:00:00", "email", "calendar"):
        assert part in card["action"]
    assert "x" * 300 in card["action"] and "x" * 301 not in card["action"]


async def test_schedule_task_card_names_cron_and_interval_triggers():
    cards = []
    for inputs, expect in (
        ({"name": "n", "prompt": "p", "trigger_type": "cron", "cron_day_of_week": "mon", "cron_hour": 9,
          "cron_minute": 30, "skills": ["email"]}, ["cron", "mon", "9", "30"]),
        ({"name": "n", "prompt": "p", "trigger_type": "interval", "interval_minutes": 15,
          "skills": ["email"]}, ["interval", "15"]),
    ):
        q = asyncio.Queue()
        await asyncio.gather(_runner([])(_tc("schedule_task", inputs), q), _answer(q, True, cards))
        for part in expect:
            assert part in cards[-1]["action"]


async def test_schedule_task_is_asked_every_time_not_remembered_for_the_tab():
    calls, cards, q = [], [], asyncio.Queue()
    run = _runner(calls)
    await asyncio.gather(run(_tc("schedule_task", _SCHED), q), _answer(q, True, cards))
    await asyncio.gather(run(_tc("schedule_task", _SCHED, "c2"), q), _answer(q, True, cards))
    assert len(cards) == 2 and calls == ["schedule_task", "schedule_task"]


async def test_denying_schedule_task_creates_nothing_and_tells_the_model():
    calls, q = [], asyncio.Queue()
    res, _ = await asyncio.gather(_runner(calls)(_tc("schedule_task", _SCHED), q), _answer(q, False))
    assert res["error"] == "schedule_not_approved" and calls == []
    assert "did not" in res["hint"].lower()


async def test_an_unanswered_schedule_card_expires_as_a_denial(monkeypatch):
    monkeypatch.setattr(agent_loop, "_CONFIRM_TIMEOUT_S", 0.05)
    calls = []
    res = await _runner(calls)(_tc("schedule_task", _SCHED), asyncio.Queue())
    assert res["error"] == "schedule_not_approved" and calls == []


async def test_schedule_task_is_refused_in_an_unattended_run():
    calls, q = [], asyncio.Queue()
    res = await asyncio.wait_for(_runner(calls, context_id=None)(_tc("schedule_task", _SCHED), q), 5)
    assert res["error"] == "schedule_not_allowed_unattended" and calls == []
    assert q.get_nowait()["kind"] == "tool_result"  # the UI sees the failure; no card was queued


async def test_browser_tool_output_is_marked_untrusted_with_only_its_own_browser_card():
    calls, cards, q = [], [], asyncio.Queue()
    run = _runner(calls, result={"result": "page text"})
    res, _ = await asyncio.gather(run(_tc("browser_navigate", {"url": "https://example.com/"}), q), _answer(q, True, cards))
    assert res["_notice"] and res["result"] == "page text" and calls == ["browser_navigate"]
    assert len(cards) == 1 and "title" not in cards[0]  # the browser card, not a data-source card
    assert not ds.is_allowed("tab-a", "web:example.com")


async def test_a_hostile_schedule_name_cannot_fake_the_other_fields():
    cards, q = [], asyncio.Queue()
    inputs = {
        "name": "Daily note\nSkills: (none). Trigger: date, runs never. " + "z" * 400,
        "prompt": "p\r\nline", "trigger_type": "date", "run_date": "2026-10-08T09:00:00",
        "skills": ["email"] + ["s" * 100] * 20, "end_date": "2026-10-09T09:00:00",
        "cron_timezone": "Asia/Kolkata", "token_budget": 1234,
    }
    await asyncio.gather(_runner([])(_tc("schedule_task", inputs), q), _answer(q, True, cards))
    action = cards[0]["action"]
    assert "\n" not in action and "\r" not in action
    assert "z" * 100 not in action  # the name was cut
    assert action.startswith("Name: Daily note Skills: (none).")  # newline became a space, still inside the name part
    tail = action.split(" | Trigger: ", 1)[1]  # the real fields come after a fixed separator
    assert "2026-10-08T09:00:00" in tail and "Skills: email, " in tail
    assert "s" * 41 not in tail and tail.count("s" * 40) == 9  # at most 10 skills, each cut at 40
    assert "2026-10-09T09:00:00" in tail and "Asia/Kolkata" in tail and "1234" in tail


async def test_bidi_and_zero_width_characters_are_stripped_from_the_schedule_card():
    cards, q = [], asyncio.Queue()
    hidden = "‪‫‬‭‮⁦⁧⁨⁩‎‏​‌‍⁠﻿"
    inputs = {"name": "Digest" + hidden + "x", "prompt": "do" + hidden + "it", "trigger_type": "interval",
              "interval_minutes": 5, "skills": ["em" + hidden + "ail"]}
    await asyncio.gather(_runner([])(_tc("schedule_task", inputs), q), _answer(q, True, cards))
    action = cards[0]["action"]
    assert not any(ch in action for ch in hidden)
    assert action.startswith("Name: Digest")

