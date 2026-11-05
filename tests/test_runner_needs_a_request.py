"""A shell/code runner is offered, and its permission card shown, only when the message asks for
something to be run. Words like "run" or "create" inside a pasted draft are not such a request."""

import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))

import app  # noqa: E402,F401
import shared  # noqa: E402
from routes import chat as chat_routes  # noqa: E402

DRAFT_REQUEST = (
    "Next: if the overnight baseline reproduces, run the SDMA on/off isolation, the XGMI "
    "patch-revert and profiling. Workaround: stay on ROCm 6.4.3.\n\n"
    "this is lot of details you can keep in key details and roll up in exec summary. "
    "Give me a revised draft"
)
CODE_REQUEST = "create a chart of last week's meetings"


def _send(monkeypatch, message, classified):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    seen = {}
    real = chat_routes._filter_tools

    def spy(active_skill, has_images, active_skills=None, **kw):
        seen["skills"] = list(active_skills or [])
        return real(active_skill, has_images, active_skills, **kw)

    monkeypatch.setattr(chat_routes, "_filter_tools", spy)
    monkeypatch.setattr(chat_routes, "_classify_skills_via_llm", lambda *a, **k: classified)
    api = FastAPI()
    api.include_router(chat_routes.router)
    with TestClient(api) as client:
        res = client.post("/api/chat", json={"message": message, "context_id": f"runner-{uuid.uuid4().hex}"})
        assert res.status_code == 200
        task_id = res.json()["task_id"]
        for _ in range(50):
            chunks = shared.chat_task_store.get_chunks(task_id)
            if "skills" in seen or (chunks and "permission_required" in chunks[0]):
                break
            time.sleep(0.1)
    chunks = shared.chat_task_store.get_chunks(task_id)
    card = json.loads(chunks[0].removeprefix("data: ").strip()) if chunks and "permission_required" in chunks[0] else None
    return seen, card


def test_the_draft_request_alone_would_have_guessed_a_runner():
    assert "code_runner" in chat_routes._infer_skills_from_message(DRAFT_REQUEST)


def test_a_rewrite_request_is_not_stopped_at_the_permission_card(monkeypatch):
    seen, card = _send(monkeypatch, DRAFT_REQUEST, classified=[])
    assert card is None
    assert "code_runner" not in seen["skills"]


def test_a_request_to_run_something_still_asks_for_permission(monkeypatch):
    seen, card = _send(monkeypatch, CODE_REQUEST, classified=["code_runner"])
    assert card and card["type"] == "permission_required"
    assert {d["id"] for d in card["deps"]} == {"code_runner"}
    assert "skills" not in seen


def test_when_the_classifier_gives_no_answer_a_guess_does_not_stop_the_turn(monkeypatch):
    seen, card = _send(monkeypatch, DRAFT_REQUEST, classified=None)
    assert card is None
    assert "code_runner" not in seen["skills"]


def test_the_model_can_still_ask_for_a_runner_when_none_was_offered():
    names = {t["name"] for t in chat_routes._filter_tools(None, False, [], unapproved_deps=[])}
    assert "request_skill" in names
    assert "run_python" not in names


def test_other_skills_from_words_are_kept_when_only_the_runner_is_dropped(monkeypatch):
    seen, card = _send(monkeypatch, "create a jira ticket for the SDMA bug", classified=[])
    assert card is None
    assert "jira" in seen["skills"] and "code_runner" not in seen["skills"]
