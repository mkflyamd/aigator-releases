"""Links and references to a service activate that service's skill, not just the browser.

A message like "see https://github.com/amd/skills" contains no skill keyword, but ".com" matches
the browser skill, which used to suppress the LLM classifier and leave GitHub unselected.
"""

import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import shared
from routes import chat
from routes.chat import _infer_skills_from_message, _needs_classifier


@pytest.mark.parametrize("message", [
    "see the repo https://github.com/amd/skills/tree/main/skills",
    "what changed in https://github.com/ROCm/rocm-systems/pull/123",
    "look at https://gist.github.com/someone/abcdef",
    "check PR #482 for me",
    "is ROCm/rocm-systems#4021 merged",
    "list my pull requests",
    "any github issues about hipcc",
])
def test_github_references_infer_github(message):
    assert "github" in _infer_skills_from_message(message)


@pytest.mark.parametrize("message", [
    "how is the weather today",
    "the pull of gravity on a 1000-lb object",
    "pr is short for press release",
    "send the report to bob",
])
def test_unrelated_messages_do_not_infer_github(message):
    assert "github" not in _infer_skills_from_message(message)


def test_github_link_still_infers_github_once_with_keyword():
    assert _infer_skills_from_message("github https://github.com/amd/skills").count("github") == 1


@pytest.mark.parametrize("message, expected", [
    ("summarize https://amd-my.sharepoint.com/:x:/g/personal/bob_amd_com/EabC", {"onedrive"}),
    ("open https://1drv.ms/x/s!AbCdEf", {"onedrive"}),
    ("read https://amd.sharepoint.com/sites/Eng/Shared%20Documents/plan.docx", {"sharepoint", "onedrive"}),
    ("what was said in https://teams.microsoft.com/l/message/19:abc@thread.v2/123", {"teams"}),
    ("summarize https://amd.slack.com/archives/C012345/p1700000000000000", {"slack"}),
])
def test_service_links_infer_that_service(message, expected):
    assert expected <= set(_infer_skills_from_message(message))


def test_needs_classifier_when_nothing_matched():
    assert _needs_classifier([], {})


def test_needs_classifier_when_only_generic_skills_matched():
    assert _needs_classifier(["browser", "code_runner"], {})
    assert _needs_classifier(["shell_runner", "file_ops"], {})


def test_specific_keyword_match_skips_classifier():
    assert not _needs_classifier(["github"], {})
    assert not _needs_classifier(["github", "browser"], {})


def test_extra_catalog_always_needs_classifier():
    assert _needs_classifier(["github"], {"g-docs": "Google Docs"})


def test_classifier_menu_describes_github_for_github_com(monkeypatch):
    skill_md = pathlib.Path(__file__).parent.parent / "web" / "skills" / "github" / "SKILL.md"
    description = re.search(r"^description: '(.*)'$", skill_md.read_text(encoding="utf-8"), re.M).group(1)
    monkeypatch.setattr(shared, "SKILL_TOOLS_MAP", {"github": {"github_get_pr"}})
    monkeypatch.setattr(shared, "SKILL_DESCRIPTIONS", {"github": description})
    monkeypatch.setattr(shared, "_BUILTIN_SKILL_IDS", {"github"})
    assert "github.com" in chat._classify_skill_ids()["github"]


def test_classifier_prompt_prefers_service_skill_over_browser_for_links():
    assert "github.com" in chat._CLASSIFY_PROMPT
    assert "browser" in chat._CLASSIFY_PROMPT


@pytest.mark.parametrize("message", [
    "what's the status of PR #482 in ROCm/rocm-systems",
    "what is the latest on https://github.com/amd/skills",
    "what is the weather today",
    "what is my IP address",
    "what's the difference between a mutex and a semaphore",
])
def test_generic_question_openers_do_not_infer_calendar(message):
    assert "calendar" not in _infer_skills_from_message(message)


@pytest.mark.parametrize("message", [
    "what's on my calendar tomorrow",
    "what is the meeting about on Friday",
    "what's the meeting at 3pm",
    "what is the invite from Bob for",
    "what's the invite on my outlook",
    "what is my next meeting",
    "what is my day like",
    "when am i free this week",
    "what meetings do I have",
])
def test_real_calendar_questions_still_infer_calendar(message):
    assert "calendar" in _infer_skills_from_message(message)
