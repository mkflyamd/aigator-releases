"""The "/" menu lists one row per skill, not one extra row for the plugin that bundles them.

A URL-installed plugin such as `motlab-assets` bundles two skills (`motlab`,
`motlab-assets`). The install record's own id is only a container, so it must not
appear next to its skills, and every row should carry a one-line description.
"""

import json
import re

import app  # noqa: F401 — importing populates shared registries
import shared
from routes import health


def _bootstrap_skills(monkeypatch, tmp_path, installed, descriptions, skill_dirs=()):
    import config
    from marketplace import installer

    monkeypatch.setattr(installer, "load_installed", lambda: installed)
    monkeypatch.setattr(config, "USER_SKILL_DIRS", list(skill_dirs))
    monkeypatch.setattr(shared, "SKILL_DESCRIPTIONS", descriptions)
    html = health._user_skills_bootstrap("")
    payload = re.search(r"window\.__USER_SKILLS__ = (.*);</script>", html, re.S).group(1)
    return json.loads(payload)


MOTLAB = {
    "id": "motlab-assets",
    "display_name": "motlab-assets",
    "tier": "Unverified",
    "skill_ids": ["motlab-assets__motlab", "motlab-assets__motlab-assets"],
}


def test_bundled_plugin_lists_its_skills_without_the_container_row(monkeypatch, tmp_path):
    skills = _bootstrap_skills(monkeypatch, tmp_path, [MOTLAB], {})
    assert [s["id"] for s in skills] == ["motlab-assets__motlab", "motlab-assets__motlab-assets"]
    assert [s["name"] for s in skills] == ["Motlab", "Motlab Assets"]


def test_plugin_without_bundled_skills_keeps_its_row(monkeypatch, tmp_path):
    single = {"id": "solo-skill", "display_name": "Solo Skill", "tier": "Community"}
    skills = _bootstrap_skills(monkeypatch, tmp_path, [single], {})
    assert [s["id"] for s in skills] == ["solo-skill"]


def test_single_top_level_skill_plugin_keeps_its_row(monkeypatch, tmp_path):
    # namespaced_skill_id() gives the bare plugin id when SKILL.md sits at the version root
    top = {"id": "one", "display_name": "One", "tier": "Community", "skill_ids": ["one"]}
    skills = _bootstrap_skills(monkeypatch, tmp_path, [top], {})
    assert [s["id"] for s in skills] == ["one"]


def test_rows_carry_a_one_line_description(monkeypatch, tmp_path):
    descriptions = {
        "motlab-assets__motlab": "Make and edit videos as code. Use whenever someone asks for a video.",
        "motlab-assets__motlab-assets": "Make reusable **assets** as code for [motlab](https://example.com) videos.",
    }
    skills = _bootstrap_skills(monkeypatch, tmp_path, [MOTLAB], descriptions)
    assert [s["description"] for s in skills] == [
        "Make and edit videos as code.",
        "Make reusable assets as code for motlab videos.",
    ]


def test_row_without_description_has_no_description_key(monkeypatch, tmp_path):
    skills = _bootstrap_skills(monkeypatch, tmp_path, [MOTLAB], {})
    assert all("description" not in s for s in skills)


def test_bare_names_from_the_skill_dir_scan_do_not_reappear(monkeypatch, tmp_path):
    for name in ("motlab", "motlab-assets"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "SKILL.md").write_text(f"---\nname: {name}\n---\nbody\n", encoding="utf-8")
    skills = _bootstrap_skills(monkeypatch, tmp_path, [MOTLAB], {}, skill_dirs=[tmp_path])
    assert [s["id"] for s in skills] == ["motlab-assets__motlab", "motlab-assets__motlab-assets"]


def test_description_is_embedded_as_json_not_raw_script(monkeypatch, tmp_path):
    hostile = {"motlab-assets__motlab": "</script><script>alert(1)</script>"}
    _bootstrap_skills(monkeypatch, tmp_path, [MOTLAB], hostile)
    html = health._user_skills_bootstrap("")
    assert html.count("</script>") == 1


def test_description_helper_caps_length_and_strips_newlines():
    long_text = "word " * 100
    out = health._one_line_description(f"line one\nline two {long_text}")
    assert "\n" not in out
    assert len(out) <= health._DESCRIPTION_MAX_CHARS
    assert out.endswith("…")
    assert health._one_line_description("") == ""


def test_skill_manager_placeholder_is_not_a_description():
    assert health._one_line_description("User skill") == ""
