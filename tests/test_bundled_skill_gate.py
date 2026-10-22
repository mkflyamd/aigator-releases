"""A bundled skill that needs shell/code execution asks for approval, can be opened by typing
its name, and is not sent down a file_ops detour when the model reads its guide."""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))

import app  # noqa: E402
import shared  # noqa: E402
from routes.chat import (  # noqa: E402
    ChatRequest,
    _blocked_gated_deps,
    _filter_tools,
    _installed_skill_ids_from_message,
    _ungranted_gated_deps,
)

RECORDER = "gator-demo-recorder"


def _req(**kw):
    return ChatRequest(message="hi", **kw)


def test_recorder_declares_its_gated_dependencies():
    ids = {d["id"] for d in shared.SKILL_DEPENDENCIES_MAP[RECORDER]}
    assert ids == {"code_runner", "shell_runner"}
    assert all(d["reason"] for d in shared.SKILL_DEPENDENCIES_MAP[RECORDER])


def test_typing_the_skill_name_activates_a_bundled_skill():
    assert RECORDER in _installed_skill_ids_from_message("lets record a demo gator-demo-recorder")
    assert RECORDER in _installed_skill_ids_from_message("open the Gator Demo Recorder please")


def test_typing_a_runner_or_plain_word_never_activates_a_bundled_skill():
    found = _installed_skill_ids_from_message(
        "use shell_runner and code_runner, shell runner, file_ops, email and calendar"
    )
    assert not {"shell_runner", "code_runner", "file_ops", "email", "calendar"} & set(found)


def test_unapproved_runner_blocks_the_recorder():
    blocked = _blocked_gated_deps([RECORDER], _req())
    assert {dep["id"] for _, dep in blocked} == {"code_runner", "shell_runner"}
    assert {sid for sid, _ in blocked} == {RECORDER}


def test_approving_one_runner_still_blocks_the_other():
    blocked = _blocked_gated_deps([RECORDER], _req(approved_deps=["shell_runner"]))
    assert [dep["id"] for _, dep in blocked] == ["code_runner"]


def test_approved_runners_unblock_the_recorder():
    req = _req(approved_deps=["shell_runner", "code_runner"])
    assert _blocked_gated_deps([RECORDER], req) == []
    assert _ungranted_gated_deps(req) == []


def test_a_skill_without_gated_dependencies_is_never_blocked():
    assert _blocked_gated_deps(["email", "calendar"], _req()) == []


def test_runner_tools_are_withheld_until_approved():
    shared.SKILL_TOOLS_MAP["shell_runner"] = {"run_shell"}
    shared.SKILL_TOOLS_MAP["code_runner"] = {"run_python"}
    shared.TOOLS.extend(
        {"name": n, "description": "t", "input_schema": {"type": "object", "properties": {}}}
        for n in ("run_shell", "run_python")
    )
    try:
        held = {
            t["name"]
            for t in _filter_tools("", False, [RECORDER], unapproved_deps=_ungranted_gated_deps(_req()))
        }
        granted = {
            t["name"]
            for t in _filter_tools(
                "", False, [RECORDER],
                unapproved_deps=_ungranted_gated_deps(_req(approved_deps=["shell_runner", "code_runner"])),
            )
        }
    finally:
        shared.TOOLS[:] = [t for t in shared.TOOLS if t["name"] not in ("run_shell", "run_python")]
        shared.SKILL_TOOLS_MAP.pop("shell_runner", None)
        shared.SKILL_TOOLS_MAP.pop("code_runner", None)
    assert not {"run_shell", "run_python"} & held
    assert {"run_shell", "run_python"} <= granted


def test_read_skill_hands_over_the_whole_guide_without_spilling_to_disk():
    guide = asyncio.run(app.execute_tool("read_skill", {"skill_id": RECORDER}))
    text = guide["skill_guide"]
    assert len(text.encode("utf-8")) > 32 * 1024
    assert "output truncated" not in json.dumps(guide)
    assert "Phase 1" in text


def _chat(monkeypatch, classified=(), **body):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import chat as chat_routes

    monkeypatch.setattr(chat_routes, "_classify_skills_via_llm", lambda *a, **k: list(classified))
    api = FastAPI()
    api.include_router(chat_routes.router)
    client = TestClient(api)
    res = client.post("/api/chat", json={"message": "lets record a demo gator-demo-recorder", **body})
    assert res.status_code == 200
    return res.json()["task_id"]


def _first_event(task_id):
    import time

    for _ in range(50):
        chunks = shared.chat_task_store.get_chunks(task_id)
        if chunks:
            return chunks[0]
        time.sleep(0.1)
    return ""


def test_typing_the_skill_name_asks_for_runner_approval(monkeypatch):
    task_id = _chat(monkeypatch)
    event = json.loads(_first_event(task_id).removeprefix("data: ").strip())
    assert event["type"] == "permission_required"
    assert event["skill"] == RECORDER
    assert {d["id"] for d in event["deps"]} == {"code_runner", "shell_runner"}


def test_a_typed_skill_name_is_not_dropped_by_the_auto_skill_cap(monkeypatch):
    from routes import chat as chat_routes

    crowd = ["code_runner", "shell_runner", "file_ops", "email", "calendar", "teams", "slack"]
    monkeypatch.setattr(chat_routes, "_available_skill_catalog", lambda: {"mcp-extra": "an installed skill"})
    monkeypatch.setattr(chat_routes, "_skill_provenance_rank", lambda sid: 4 if sid == RECORDER else 0)
    task_id = _chat(monkeypatch, classified=crowd)
    event = json.loads(_first_event(task_id).removeprefix("data: ").strip())
    assert event["type"] == "permission_required"
    assert event["skill"] == RECORDER


def test_permission_card_is_not_overwritten_by_the_stream_end_render():
    src = open(os.path.join(os.path.dirname(__file__), "..", "web", "static", "app.js"), encoding="utf-8").read()
    assert src.count("if (_permissionCardShown) return;") == 2
    assert "if (!_permissionCardShown) prose.innerHTML = _renderProse();" in src
    assert "_permissionCardShown = true;\n              _renderPermissionCard(" in src
    reset = src.index("    _userCollapsedThinking = false;\n    _permissionCardShown = false;")
    assert src.index("const doSend = async (overridePayload) => {") < reset


def test_recorder_guide_does_not_preflight_from_the_sandbox():
    guide = open(
        os.path.join(os.path.dirname(__file__), "..", "web", "skills", RECORDER, "SKILL.md"), encoding="utf-8"
    ).read()
    assert "preflight.py" not in guide
    assert "/api/recorder/preflight" not in guide
    assert ".gator/skills/mine/gator-demo-recorder/scripts" not in guide
