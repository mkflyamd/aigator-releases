import importlib

import pytest

from marketplace import installer

SHARE_SOURCE = {"drive_id": "d1", "folder_id": "f1"}


@pytest.fixture
def tools(tmp_path, monkeypatch):
    monkeypatch.setattr("config.INSTALLED_SKILLS_DIR", tmp_path)
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    import skills.skill_manager.tools as m

    importlib.reload(m)
    yield m
    importlib.reload(m)


def _install(tmp_path, skill_id, tier, share_source=None):
    folder = tmp_path / ("mine" if tier == "Mine" else "") / skill_id
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        f'---\nname: {skill_id}\ndescription: "d"\nversion: "1"\n---\n\nOriginal.',
        encoding="utf-8",
    )
    entry = {"id": skill_id, "version": "1", "tier": tier}
    if share_source:
        entry["share_source"] = share_source
    installer.save_installed([*installer.load_installed(), entry])
    return folder / "SKILL.md"


def test_a_received_skill_cannot_be_edited(tools, tmp_path):
    skill_md = _install(tmp_path, "weekly-report", "Community", SHARE_SOURCE)
    before = skill_md.read_text(encoding="utf-8")

    result = tools._tool_update_skill("weekly-report", "Changed.")

    assert "error" in result
    assert "shared with you" in result["error"]
    assert skill_md.read_text(encoding="utf-8") == before


def test_the_authors_own_shared_skill_can_still_be_edited(tools, tmp_path):
    skill_md = _install(tmp_path, "weekly-report", "Mine", SHARE_SOURCE)

    result = tools._tool_update_skill("weekly-report", "Changed.")

    assert result.get("ok") is True, result
    assert skill_md.read_text(encoding="utf-8").endswith("Changed.")


def test_a_mine_skill_that_was_never_shared_can_be_edited(tools, tmp_path):
    skill_md = _install(tmp_path, "weekly-report", "Mine")

    assert tools._tool_update_skill("weekly-report", "Changed.").get("ok") is True
    assert skill_md.read_text(encoding="utf-8").endswith("Changed.")


def test_an_installed_skill_that_was_not_shared_keeps_its_old_behaviour(tools, tmp_path):
    skill_md = _install(tmp_path, "from-marketplace", "Community")

    assert tools._tool_update_skill("from-marketplace", "Changed.").get("ok") is True
    assert skill_md.read_text(encoding="utf-8").endswith("Changed.")
