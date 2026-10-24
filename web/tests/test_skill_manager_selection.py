"""Asking to create or edit a skill selects Skill Manager, so create_skill is offered instead of a schedule being made."""

import app  # noqa: F401 — populates registries
from routes import chat


def test_a_request_to_create_a_skill_selects_skill_manager():
    msg = "can you help create a skill to run weekly on Friday noon over my meetings and recap them in OneNote"
    assert "skill_manager" in chat._infer_skills_from_message(msg)


def test_a_request_to_edit_a_skill_selects_skill_manager():
    assert "skill_manager" in chat._infer_skills_from_message("update my skill so it skips focus time")


def test_other_create_requests_do_not_select_it():
    assert "skill_manager" not in chat._infer_skills_from_message("create a chart of last week's meetings")


def test_selecting_it_offers_create_skill():
    offered = {t["name"] for t in chat._filter_tools(None, False, ["skill_manager"])}
    assert {"create_skill", "update_skill"} <= offered
