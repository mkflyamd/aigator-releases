"""update_skill rewrote the whole frontmatter, so a skill's description reset to "User skill" and a
`requires:` list could not be set or survive an edit; a skill that needs calendar/teams tools then ran
without them."""
import importlib

import pytest


@pytest.fixture
def tools(tmp_path, monkeypatch):
    monkeypatch.setattr("config.INSTALLED_SKILLS_DIR", tmp_path)
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    import skills.skill_manager.tools as m

    importlib.reload(m)
    yield m
    importlib.reload(m)


def _md(tmp_path, sid):
    return (tmp_path / "mine" / sid / "SKILL.md").read_text(encoding="utf-8")


def test_create_skill_writes_description_and_requires(tools, tmp_path):
    r = tools._tool_create_skill("recap-x", "Recap X", "Steps.", description="Recap the week", requires=["calendar", "teams"])
    assert r.get("ok") is True, r
    text = _md(tmp_path, "recap-x")
    assert 'description: "Recap the week"' in text
    assert "requires: [calendar, teams]" in text
    assert tools.shared._parse_skill_requires(tmp_path / "mine" / "recap-x" / "SKILL.md") == ["calendar", "teams"]
    assert tools.shared._parse_skill_description(tmp_path / "mine" / "recap-x" / "SKILL.md") == "Recap the week"


def test_update_keeps_description_and_requires_when_not_given(tools, tmp_path):
    tools._tool_create_skill("recap-x", "Recap X", "Steps.", description="Recap the week", requires=["calendar"])
    r = tools._tool_update_skill("recap-x", "New steps.")
    assert r.get("ok") is True, r
    text = _md(tmp_path, "recap-x")
    assert 'description: "Recap the week"' in text and "requires: [calendar]" in text
    assert text.endswith("New steps.")


def test_update_can_set_and_clear_description_and_requires(tools, tmp_path):
    tools._tool_create_skill("recap-x", "Recap X", "Steps.")
    assert 'description: "User skill"' in _md(tmp_path, "recap-x")
    tools._tool_update_skill("recap-x", "Steps.", description='Say "hi"\nnow', requires=["onedrive", "onenote"])
    text = _md(tmp_path, "recap-x")
    assert "description: \"Say 'hi' now\"" in text and "requires: [onedrive, onenote]" in text
    tools._tool_update_skill("recap-x", "Steps.", requires=[])
    assert "requires:" not in _md(tmp_path, "recap-x")


@pytest.mark.parametrize("bad", [["code_runner"], ["shell_runner"], ["no-such-skill"], ["recap-x"], "calendar"])
def test_requires_rejects_runners_unknown_self_and_non_lists(tools, tmp_path, bad):
    tools._tool_create_skill("recap-x", "Recap X", "Steps.", requires=["calendar"])
    r = tools._tool_update_skill("recap-x", "Steps.", requires=bad)
    assert "error" in r
    assert "requires: [calendar]" in _md(tmp_path, "recap-x")
    assert "error" in tools._tool_create_skill("recap-y", "Recap Y", "Steps.", requires=["code_runner"])
    assert not (tmp_path / "mine" / "recap-y").exists()


def test_tool_schemas_offer_description_and_requires(tools):
    for d in tools.TOOL_DEFS:
        if d["name"] in ("create_skill", "update_skill"):
            props = d["input_schema"]["properties"]
            assert "description" in props and props["requires"]["type"] == "array"
