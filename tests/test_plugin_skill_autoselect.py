"""#3: marketplace *plugin*-bundle skills are loaded into SKILL_PROMPTS but are
NOT recorded in installed-skills.json. Before the fix, the skill classifier
catalog and the name matcher both iterated only installed-skills.json, so plugin
skills were invisible to auto-selection (activatable only by explicit mention).

These tests pin the fix: a skill present in SKILL_PROMPTS + SKILL_DESCRIPTIONS
but absent from installed-skills.json must be offered to the classifier and must
match a plain name mention.
"""

import os
import sys
import pathlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))

import shared
from routes import chat


# ── _parse_skill_description ────────────────────────────────────────────────


def _write_skill_md(tmp_path, frontmatter: str) -> pathlib.Path:
    p = tmp_path / "SKILL.md"
    p.write_text(f"---\n{frontmatter}\n---\n\n# Body\n", encoding="utf-8")
    return p


def test_parse_description_plain_scalar(tmp_path):
    p = _write_skill_md(tmp_path, "name: x\ndescription: A short one-line description.")
    assert shared._parse_skill_description(p) == "A short one-line description."


def test_parse_description_quoted_scalar(tmp_path):
    p = _write_skill_md(tmp_path, 'name: x\ndescription: "quoted desc"')
    assert shared._parse_skill_description(p) == "quoted desc"


def test_parse_description_folded_block(tmp_path):
    # The `>-` folded form the marketplace plugin skills actually use.
    fm = (
        "name: x\n"
        "description: >-\n"
        "  Routes image generation through a local\n"
        "  Lemonade Server. Use for local image gen.\n"
        "license: Proprietary"
    )
    p = _write_skill_md(tmp_path, fm)
    got = shared._parse_skill_description(p)
    assert (
        got
        == "Routes image generation through a local Lemonade Server. Use for local image gen."
    )
    assert "license" not in got  # must stop at the next top-level key


def test_parse_description_absent(tmp_path):
    p = _write_skill_md(tmp_path, "name: x\nrequires: [email]")
    assert shared._parse_skill_description(p) == ""


# ── catalog + name matcher include plugin-cache skills ──────────────────────

_FAKE_ID = "vendor-plugin__widget-maker"


def _inject_plugin_skill(monkeypatch):
    """Add a synthetic plugin skill to the live registries the way the loader
    would for a plugin-cache bundle: in SKILL_PROMPTS + SKILL_DESCRIPTIONS, but
    deliberately NOT in installed-skills.json (load_installed)."""
    prompts = dict(shared.SKILL_PROMPTS)
    descs = dict(shared.SKILL_DESCRIPTIONS)
    prompts[_FAKE_ID] = "# Widget Maker\nDoes widget things."
    descs[_FAKE_ID] = "Builds and previews widgets from a spec."
    monkeypatch.setattr(shared, "SKILL_PROMPTS", prompts)
    monkeypatch.setattr(shared, "SKILL_DESCRIPTIONS", descs)
    # load_installed() must NOT contain it — that's the whole point.
    monkeypatch.setattr("marketplace.installer.load_installed", lambda: [])


def test_plugin_skill_appears_in_classifier_catalog(monkeypatch):
    _inject_plugin_skill(monkeypatch)
    cat = chat._installed_skill_catalog()
    assert _FAKE_ID in cat, "plugin-cache skill must be offered to the classifier"
    assert "widget" in cat[_FAKE_ID].lower()
    # And it must survive into the combined catalog fed to the LLM/manifest.
    assert _FAKE_ID in chat._available_skill_catalog()


def test_plugin_skill_matches_name_mention(monkeypatch):
    _inject_plugin_skill(monkeypatch)
    # Bare last-segment mention (what a user actually types).
    assert _FAKE_ID in chat._installed_skill_ids_from_message(
        "can you use widget-maker for this?"
    )
    # Full namespaced id also matches.
    assert _FAKE_ID in chat._installed_skill_ids_from_message(f"use {_FAKE_ID} please")


def test_unrelated_message_does_not_match_plugin_skill(monkeypatch):
    _inject_plugin_skill(monkeypatch)
    assert _FAKE_ID not in chat._installed_skill_ids_from_message(
        "what meetings do I have tomorrow?"
    )


def test_builtin_skills_not_double_listed(monkeypatch):
    """A built-in must not be pulled into the installed catalog by the new
    plugin-cache pass (built-ins are routed via _CLASSIFY_SKILL_IDS)."""
    _inject_plugin_skill(monkeypatch)
    cat = chat._installed_skill_catalog()
    for bid in shared._BUILTIN_SKILL_IDS:
        assert bid not in cat, f"built-in {bid} leaked into installed catalog"
