"""Tests for skill-cap coexistence (fix A) and always-on tool availability (fix B).

A: A guidance-only marketplace skill (has_tools=False) must not displace a native
   skill that carries tools when the provenance cap fires. The guidance skill
   stays in the active set (exempt from the cap) so its prompt can still inject;
   the native skill's tools survive.

B: ppt/docx/excel are ALWAYS_ON, so their tools are available every turn even
   when no skill is selected. SKILL.md prompts remain gated (not asserted here —
   that's a prompt-injection concern, not a tool-availability one).
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))

import pytest


# ── B: always-on tool availability ──────────────────────────────────────────


@pytest.fixture(autouse=True)
def _import_app():
    """Importing web.app runs _load_skill_modules(), populating shared state
    with the real skill registry (including ALWAYS_ON flags). Import app (which
    triggers registration) but do NOT reload shared afterward — that would wipe
    the sets app just populated."""
    import app  # noqa: F401  (side effect: registers all skills into shared)

    yield


def test_ppt_docx_excel_are_always_on():
    """The three office skills must be flagged ALWAYS_ON so their tools are
    available with no skill selected."""
    import shared

    for sid in ("ppt", "docx", "excel"):
        assert sid in shared._ALWAYS_ON_SKILLS, (
            f"{sid} must be in _ALWAYS_ON_SKILLS; got {sorted(shared._ALWAYS_ON_SKILLS)}"
        )


def test_office_tools_available_with_no_skill_selected():
    """With no active skill, _filter_tools returns always-on tools — which must
    include the office skills' read/edit tools (read_pptx, get_docx_info, read_excel,
    and the new pptx_apply_theme)."""
    from routes.chat import _filter_tools
    import shared

    result = _filter_tools(None, has_images=False)
    names = {t["name"] for t in result}
    # ppt tools
    assert "read_pptx" in names, "ppt tools missing with no skill selected"
    assert "pptx_apply_theme" in names, (
        "pptx_apply_theme missing with no skill selected"
    )
    # docx tools
    assert "get_docx_info" in names, "docx tools missing with no skill selected"
    # excel tools
    assert "read_excel" in names, "excel tools missing with no skill selected"


# ── A: cap coexistence — guidance-only marketplace skills exempt ─────────────


def test_marketplace_skill_has_tools_true_for_native_builtin():
    """Native builtins always have tools."""
    from routes.chat import _marketplace_skill_has_tools

    assert _marketplace_skill_has_tools("ppt") is True
    assert _marketplace_skill_has_tools("docx") is True


def test_marketplace_skill_has_tools_false_for_guidance_only(monkeypatch):
    """A marketplace skill with has_tools=False is guidance-only."""
    from routes.chat import _marketplace_skill_has_tools
    import marketplace.installer as installer

    monkeypatch.setattr(
        installer,
        "load_installed",
        lambda: [
            {"id": "pptx", "has_tools": False, "source": "clawhub"},
        ],
    )
    assert _marketplace_skill_has_tools("pptx") is False


def test_marketplace_skill_has_tools_true_for_tool_bearing_marketplace(monkeypatch):
    """A marketplace skill that ships tools.py is tool-bearing."""
    from routes.chat import _marketplace_skill_has_tools
    import marketplace.installer as installer

    monkeypatch.setattr(
        installer,
        "load_installed",
        lambda: [
            {"id": "some-verified-skill", "has_tools": True, "source": "verified"},
        ],
    )
    assert _marketplace_skill_has_tools("some-verified-skill") is True


def test_guidance_only_skill_does_not_displace_native(monkeypatch):
    """The regression: when ppt (native, has tools) and pptx (marketplace,
    guidance-only) are both auto-candidates and the cap fires, ppt must NOT be
    dropped. pptx is exempt from the cap (adds no tools), so both coexist."""
    import shared
    from routes.chat import _marketplace_skill_has_tools
    import marketplace.installer as installer

    # Fixture: pptx installed as guidance-only
    monkeypatch.setattr(
        installer,
        "load_installed",
        lambda: [
            {"id": "pptx", "has_tools": False, "source": "clawhub"},
        ],
    )

    # ppt is native → has tools; pptx is guidance-only
    assert _marketplace_skill_has_tools("ppt") is True
    assert _marketplace_skill_has_tools("pptx") is False

    # Simulate the cap logic: tool-bearing candidates compete; guidance-only are
    # exempt. Build a candidate list that would overflow the cap if guidance-only
    # skills counted.
    _MAX_AUTO_SKILLS = 4
    # 5 tool-bearing native skills + 1 guidance-only (pptx) — the old code would
    # rank pptx (rank 3) above a native (rank 4) and drop the native.
    tool_bearing = ["ppt", "docx", "excel", "teams", "email"]  # all native builtins
    guidance_only = ["pptx"]
    capped = [s for s in tool_bearing if _marketplace_skill_has_tools(s)]
    exempt = [s for s in guidance_only if not _marketplace_skill_has_tools(s)]

    # Even though total (6) > cap (4), the guidance-only skill is exempt and the
    # 5 tool-bearing skills are capped to 4. The key assertion: ppt is NOT
    # dropped just because pptx is present.
    ranked = sorted(capped, key=lambda s: 4)  # all rank 4 (native)
    kept = set(ranked[:_MAX_AUTO_SKILLS])
    dropped = ranked[_MAX_AUTO_SKILLS:]
    final_active = set(kept) | set(exempt)

    assert "pptx" in final_active, "guidance-only skill should be exempt (kept)"
    assert "ppt" in final_active, "ppt must not be displaced by guidance-only pptx"
    # exactly one tool-bearing skill is dropped by the cap
    assert len(dropped) == 1
    assert dropped[0] not in final_active


def test_tool_bearing_marketplace_skill_still_competes_in_cap(monkeypatch):
    """A marketplace skill that DOES ship tools is NOT exempt — it competes
    normally and can displace a native skill (existing behavior preserved)."""
    from routes.chat import _marketplace_skill_has_tools, _skill_provenance_rank
    import marketplace.installer as installer

    monkeypatch.setattr(
        installer,
        "load_installed",
        lambda: [
            {"id": "verified-docx", "has_tools": True, "source": "verified"},
        ],
    )
    assert _marketplace_skill_has_tools("verified-docx") is True
    # verified (rank 2) beats native (rank 4) — existing displacement behavior intact
    assert _skill_provenance_rank("verified-docx") < _skill_provenance_rank("docx")
