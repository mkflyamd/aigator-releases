"""An instruction-only skill's steps name tools (and /skills) that live in other skills. Without those
loaded the model cannot follow the steps and the turn ends with "I need the calendar tools first".
The skills a skill's text names are loaded with it, so no author has to know to declare them."""
import pytest

import app  # noqa: F401  (builds the tool registry)
import shared
from routes import chat


@pytest.fixture
def skill(monkeypatch):
    def make(body, sid="recap-x", requires=None):
        monkeypatch.setitem(shared.SKILL_PROMPTS, sid, body)
        if requires is not None:
            monkeypatch.setitem(shared.SKILL_REQUIRES, sid, requires)
        return sid
    return make


def test_tools_named_in_the_steps_load_the_skills_that_own_them(skill):
    sid = skill("Call find_meeting_transcripts, then create_onenote_page for each meeting.")
    needed = chat._skill_requires(sid)
    assert "teams" in needed and "onenote" in needed


def test_a_slash_skill_named_in_the_steps_is_loaded(skill):
    sid = skill("Activate `/calendar` and read the last 7 days.")
    assert chat._skill_requires(sid) == ["calendar"]


def test_urls_and_paths_are_not_taken_for_skills(skill):
    sid = skill("See https://example.com/calendar and C:/tmp/calendar and docs/calendar/x.")
    assert chat._skill_requires(sid) == []


def test_declared_requires_come_first_without_duplicates(skill):
    sid = skill("Use /calendar then /teams.", requires=["teams"])
    assert chat._skill_requires(sid) == ["teams", "calendar"]


def test_runners_are_never_added(skill):
    sid = skill("Run run_python and run_shell, or use /code_runner and /shell_runner.")
    assert chat._skill_requires(sid) == []


def test_always_on_tools_and_the_skill_itself_add_nothing(skill):
    sid = skill("Use ask_user, read_skill and /recap-x.")
    assert chat._skill_requires(sid) == []


def test_a_bundle_never_stands_in_for_the_specific_skill(skill):
    sid = skill("Call create_docx and create_excel.")
    needed = chat._skill_requires(sid)
    assert set(needed) == {"docx", "excel"}
    assert not set(needed) & {"gator", "aigator"}


def test_built_in_skills_load_exactly_what_they_declare():
    for sid in shared._BUILTIN_SKILL_IDS:
        assert chat._skill_requires(sid) == shared.SKILL_REQUIRES.get(sid, [])


def test_every_built_in_tool_belongs_to_a_loadable_skill():
    # A skill naming one of these tools can only get it if some loadable skill offers it.
    for sid in shared._BUILTIN_SKILL_IDS:
        for tool in shared.SKILL_TOOLS_MAP.get(sid, set()) - shared._ALWAYS_ON_TOOLS:
            if chat._is_gated_runner(sid):
                continue
            assert chat._skills_that_provide({tool}), f"{tool} ({sid}) is offered by no loadable skill"


def test_installed_skills_have_every_skill_they_name_available():
    # Whatever instruction-only skills are installed here: nothing they name may resolve to a skill
    # that would be dropped at load time.
    for sid in shared.SKILL_PROMPTS:
        if sid in shared._BUILTIN_SKILL_IDS:
            continue
        for dep in chat._skill_requires(sid):
            assert dep in shared.SKILL_PROMPTS, f"{sid} needs {dep}, which is not a loadable skill"


def test_loader_and_request_skill_use_the_derived_list():
    from pathlib import Path
    web = Path(chat.__file__).parent.parent
    chat_src = (web / "routes" / "chat.py").read_text(encoding="utf-8")
    loop_src = (web / "agent_loop.py").read_text(encoding="utf-8")
    assert "shared.SKILL_REQUIRES.get(_seed" not in chat_src and "_skill_requires(_seed)" in chat_src
    assert "_shared.SKILL_REQUIRES.get(seed" not in loop_src and "_skill_requires(seed)" in loop_src
