"""A chat that already ran code keeps the code runner when a later message names a skill, and a
model that asks for a skill that is already on is told so instead of the turn ending empty."""

import asyncio
import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))

import app  # noqa: E402,F401
import pytest  # noqa: E402
import shared  # noqa: E402
from routes import chat as chat_routes  # noqa: E402
from routes.chat import (  # noqa: E402
    _already_active_note,
    _already_active_skill_requests,
    _detect_requested_skills,
    _gated_runners_for_tools,
)


@pytest.fixture
def runners(monkeypatch):
    monkeypatch.setitem(shared.SKILL_TOOLS_MAP, "shell_runner", {"run_shell"})
    monkeypatch.setitem(shared.SKILL_TOOLS_MAP, "code_runner", {"run_python"})
    for n in ("run_shell", "run_python"):
        monkeypatch.setattr(
            shared, "TOOLS",
            [*shared.TOOLS, {"name": n, "description": "t", "input_schema": {"type": "object", "properties": {}}}],
        )


def test_only_runners_whose_tools_ran_are_carried(runners):
    assert _gated_runners_for_tools({"run_python", "slack_search_public_and_private"}) == ["code_runner"]
    assert _gated_runners_for_tools({"run_shell", "run_python"}) == ["code_runner", "shell_runner"]
    assert _gated_runners_for_tools({"slack_search_public_and_private"}) == []
    assert _gated_runners_for_tools(None) == []


def _seed_run_python(ctx):
    msgs = [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "run_python", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
    ]
    asyncio.run(shared.conversation_store.append(ctx, msgs))


def _offered_skills(monkeypatch, message, seeded):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    ctx = f"carry-{uuid.uuid4().hex}"
    if seeded:
        _seed_run_python(ctx)
    seen = {}
    real = chat_routes._filter_tools

    def spy(active_skill, has_images, active_skills=None, **kw):
        seen["skills"] = list(active_skills or [])
        seen["tools"] = [t["name"] for t in real(active_skill, has_images, active_skills, **kw)]
        return real(active_skill, has_images, active_skills, **kw)

    monkeypatch.setattr(chat_routes, "_filter_tools", spy)
    monkeypatch.setattr(chat_routes, "_classify_skills_via_llm", lambda *a, **k: [])
    api = FastAPI()
    api.include_router(chat_routes.router)
    with TestClient(api) as client:
        res = client.post("/api/chat", json={"message": message, "context_id": ctx})
        assert res.status_code == 200
        for _ in range(50):
            if "skills" in seen:
                break
            time.sleep(0.1)
    return seen


def test_naming_a_skill_keeps_the_runner_the_chat_already_used(runners, monkeypatch):
    seen = _offered_skills(monkeypatch, "check my slack messages", seeded=True)
    assert "code_runner" in seen["skills"]
    assert "run_python" in seen["tools"]


def test_a_message_with_no_signal_keeps_the_runner(runners, monkeypatch):
    seen = _offered_skills(monkeypatch, "proceed", seeded=True)
    assert "code_runner" in seen["skills"] and "run_python" in seen["tools"]


def test_a_chat_that_never_ran_code_is_not_given_the_runner(runners, monkeypatch):
    seen = _offered_skills(monkeypatch, "check my slack messages", seeded=False)
    assert "code_runner" not in seen["skills"]
    assert "run_python" not in seen["tools"]


def test_a_model_still_cannot_grant_itself_a_runner(runners):
    assert _detect_requested_skills("/code_runner", []) == []
    assert _detect_requested_skills("/shell_runner", ["ppt"]) == []


def test_a_bare_skill_turn_for_an_active_skill_is_recognised():
    assert _already_active_skill_requests("/code_runner", ["code_runner", "ppt"]) == ["code_runner"]
    assert _already_active_skill_requests("  /ppt\n/code_runner ", ["code_runner", "ppt"]) == ["ppt", "code_runner"]


def test_a_skill_token_on_its_own_line_inside_prose_is_recognised():
    turn = "I'll set up the schedule first.\n\n/calendar\n\nI need the calendar skill active.\nNothing will be sent."
    assert _already_active_skill_requests(turn, ["calendar", "teams"]) == ["calendar"]


def test_prose_or_inactive_skills_are_not_treated_as_a_stall():
    assert _already_active_skill_requests("I will use /code_runner for this", ["code_runner"]) == []
    assert _already_active_skill_requests("Done. See ./out/code.py", ["code_runner"]) == []
    assert _already_active_skill_requests("/jira", ["code_runner"]) == []
    assert _already_active_skill_requests("", ["code_runner"]) == []


def test_the_note_lists_the_tools_it_can_actually_use(runners):
    note = _already_active_note(["code_runner"], {"run_python", "other"})
    assert "run_python" in note and "already active" in note
    held = _already_active_note(["code_runner"], {"other"})
    assert "run_python" not in held and "none of its tools" in held


def test_the_loop_answers_an_already_active_request_instead_of_ending(runners, monkeypatch):
    import agent_loop
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    calls = []

    def fake_loop(**kw):
        calls.append({**kw, "msgs": list(kw["msgs"])})
        said = "/code_runner" if len(calls) == 1 else "Running it now."
        kw["msgs"].append({"role": "assistant", "content": [{"type": "text", "text": said}]})

        async def gen():
            yield f"data: {json.dumps({'token': said})}\n\n"
            yield "data: [DONE]\n\n"

        return gen()

    ctx = f"carry-{uuid.uuid4().hex}"
    _seed_run_python(ctx)
    monkeypatch.setattr(agent_loop, "_single_agent_loop", fake_loop)
    monkeypatch.setattr(chat_routes, "_classify_skills_via_llm", lambda *a, **k: [])
    api = FastAPI()
    api.include_router(chat_routes.router)
    with TestClient(api) as client:
        task_id = client.post("/api/chat", json={"message": "proceed", "context_id": ctx}).json()["task_id"]
        for _ in range(100):
            if any("[DONE]" in c for c in shared.chat_task_store.get_chunks(task_id)) and len(calls) >= 2:
                break
            time.sleep(0.1)

    assert len(calls) == 2, "the empty skill-name turn must be retried, not ended"
    retry = calls[1]["msgs"]
    assert [m["role"] for m in retry[-3:]].count("assistant") == 1
    assert retry[-2]["role"] == "assistant" and retry[-1]["role"] == "user"
    assert "run_python" in retry[-1]["content"] and "already active" in retry[-1]["content"]
    assert "run_python" in {t["name"] for t in calls[1]["normalized_tools"]}


def _run_scripted_loop(monkeypatch, first_run_chunks, expected_calls):
    import agent_loop
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    calls = []

    def fake_loop(**kw):
        calls.append({**kw, "msgs": list(kw["msgs"])})
        chunks = first_run_chunks if len(calls) == 1 else [{"token": "Running it now."}]
        said = "".join(c.get("token", "") for c in chunks)
        kw["msgs"].append({"role": "assistant", "content": [{"type": "text", "text": said}]})

        async def gen():
            for c in chunks:
                yield f"data: {json.dumps(c)}\n\n"
            yield "data: [DONE]\n\n"

        return gen()

    ctx = f"carry-{uuid.uuid4().hex}"
    _seed_run_python(ctx)
    monkeypatch.setattr(agent_loop, "_single_agent_loop", fake_loop)
    monkeypatch.setattr(chat_routes, "_classify_skills_via_llm", lambda *a, **k: [])
    api = FastAPI()
    api.include_router(chat_routes.router)
    with TestClient(api) as client:
        task_id = client.post("/api/chat", json={"message": "proceed", "context_id": ctx}).json()["task_id"]
        for _ in range(100):
            if any("[DONE]" in c for c in shared.chat_task_store.get_chunks(task_id)) and len(calls) >= expected_calls:
                break
            time.sleep(0.1)
        time.sleep(0.3)
    return calls


TOOL_DONE = {"tool_result": {"call_id": "c1", "status": "ok", "summary": "read"}}


def test_a_skill_line_after_the_last_tool_result_is_retried(runners, monkeypatch):
    calls = _run_scripted_loop(
        monkeypatch,
        [TOOL_DONE, {"token": "Plan first.\n\n/code_runner\n\nI need it active."}],
        expected_calls=2,
    )
    assert len(calls) == 2
    assert "already active" in calls[1]["msgs"][-1]["content"]


def test_a_skill_line_before_later_tool_work_is_not_retried(runners, monkeypatch):
    calls = _run_scripted_loop(
        monkeypatch,
        [{"token": "/code_runner\n"}, TOOL_DONE, {"token": "All done."}],
        expected_calls=2,
    )
    assert len(calls) == 1


def test_a_runner_alias_cannot_be_self_granted_or_carried_as_a_plain_skill():
    aliases = [s for s in shared.SKILL_TOOLS_MAP if s in ("code-runner", "python-runner")]
    assert aliases, "code_runner registers aliases"
    for alias in aliases:
        assert _detect_requested_skills(f"/{alias}", []) == []
        assert alias not in chat_routes._skills_for_tools(shared.SKILL_TOOLS_MAP[alias])
