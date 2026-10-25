from pathlib import Path

import pytest

import narration_approval as na
import skill_pin as sp

CHAT_SRC = (Path(__file__).resolve().parents[2] / "web" / "routes" / "chat.py").read_text("utf-8")
KNOWN = {"gator-demo-recorder": "prompt", "jira": "prompt"}


def test_resolve_pin_accepts_known_skill_and_valid_id():
    pin = sp.resolve_pin("gator-demo-recorder", "demo_20261019_101500", KNOWN)
    assert pin == sp.Pin("gator-demo-recorder", "demo_20261019_101500")


def test_resolve_pin_drops_unknown_skill():
    assert sp.resolve_pin("not-a-skill", "demo_1", KNOWN) is None
    assert sp.resolve_pin(None, None, KNOWN) is None
    assert sp.resolve_pin(5, None, KNOWN) is None


@pytest.mark.parametrize("bad", ["../etc", "a/b", "a b", "x" * 81, "", "demo\n1"])
def test_resolve_pin_drops_bad_project_id_but_keeps_skill(bad):
    assert sp.resolve_pin("gator-demo-recorder", bad, KNOWN) == sp.Pin("gator-demo-recorder", None)


def test_resolve_pin_inactive_for_slash_commands():
    assert sp.resolve_pin("gator-demo-recorder", "demo_1", KNOWN, slash_active=True) is None


def test_context_block_for_demo_project(store):
    p = store.create_project()
    na.approve(p["project_id"], [{"text": "hello"}], {})
    block = sp.pin_context_block(sp.Pin("gator-demo-recorder", p["project_id"]))
    assert f"PINNED PROJECT: {p['name']} ({p['project_id']})" in block
    assert f"PROJECT_DIR: {p['path']}" in block
    assert "Current narration approval: appr_1_" in block
    assert "Do not look up the active project." in block


def test_context_block_empty_cases(store):
    assert sp.pin_context_block(None) == ""
    assert sp.pin_context_block(sp.Pin("gator-demo-recorder", None)) == ""
    assert sp.pin_context_block(sp.Pin("jira", "x")) == ""
    assert sp.pin_context_block(sp.Pin("gator-demo-recorder", "demo_19990101_000000")) == ""


def test_chat_request_has_pin_fields():
    from routes.chat import ChatRequest
    fields = getattr(ChatRequest, "model_fields", None) or ChatRequest.__fields__
    assert "pinned_skill" in fields and "pinned_project_id" in fields


def test_chat_source_wires_the_pin():
    assert "pinned_skill: str | None = None" in CHAT_SRC
    assert "pinned_project_id: str | None = None" in CHAT_SRC
    assert "_resolve_pin(req.pinned_skill, req.pinned_project_id" in CHAT_SRC
    assert "_skills_locked = bool(req.scoped_skill or _pin)" in CHAT_SRC
    assert "_pin_context_block(_pin)" in CHAT_SRC
    assert "_inject_skill = req.scoped_skill or (_pin.skill if _pin else None)" in CHAT_SRC


def test_chat_source_gates_use_skills_locked():
    assert "not req.scoped_skill" not in CHAT_SRC
    assert CHAT_SRC.count("_skills_locked") >= 5
    assert "if _skills_locked:\n        print(f\"[classifier] skipped" in CHAT_SRC
    assert "if not _classifier_inherited and not _skills_locked:" in CHAT_SRC
    assert "_image_analysis_requested = not _skills_locked and" in CHAT_SRC
    assert "    if not _skills_locked:\n        _inferred = _ensure_image_fetch_skill(" in CHAT_SRC
