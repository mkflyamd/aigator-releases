"""The classifier menu is derived from the skills, so no user-facing built-in skill can be missing from it."""

import app  # noqa: F401 — populates registries
import shared
from routes import chat


def _user_facing_builtins():
    return {
        sid for sid in shared._BUILTIN_SKILL_IDS
        if shared.SKILL_TOOLS_MAP.get(sid) and sid not in shared.SKILL_CLASSIFY_OPT_OUT
    }


def test_every_user_facing_builtin_skill_with_tools_is_in_the_menu():
    menu = chat._classify_skill_ids()
    missing = _user_facing_builtins() - set(menu)
    assert not missing


def test_every_menu_entry_has_a_real_description_that_is_not_cut_off():
    for sid in _user_facing_builtins():
        desc = shared.SKILL_DESCRIPTIONS.get(sid, "")
        assert desc, f"{sid}: add a description to its SKILL.md frontmatter, or set `classify: false`"
        assert len(desc) <= chat._CLASSIFY_DESC_MAX, f"{sid}: description longer than the menu allows"
        assert chat._classify_skill_ids()[sid] == desc


def test_a_skill_is_left_out_only_by_an_explicit_flag_in_its_skill_md():
    menu = chat._classify_skill_ids()
    flagged = {
        d.name for d in (shared._WEB_DIR / "skills").iterdir()
        if (d / "SKILL.md").is_file() and shared._parse_skill_classify(d / "SKILL.md") is False
    }
    assert flagged == shared.SKILL_CLASSIFY_OPT_OUT
    assert not flagged & set(menu)


def test_skills_that_were_missing_are_now_offered():
    menu = chat._classify_skill_ids()
    assert "onedrive" in menu and "people" in menu and "skill_manager" in menu
    assert "transcript" in menu["teams"].lower()


def test_the_flag_parser_reads_frontmatter(tmp_path):
    f = tmp_path / "SKILL.md"
    f.write_text("---\nname: x\nclassify: false\n---\nbody", encoding="utf-8")
    assert shared._parse_skill_classify(f) is False
    f.write_text("---\nname: x\n---\nclassify: false", encoding="utf-8")
    assert shared._parse_skill_classify(f) is True
