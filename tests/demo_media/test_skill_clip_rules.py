from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "web" / "skills" / "gator-demo-recorder" / "SKILL.md"


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _import_section() -> str:
    return _text().split("## Import Mode", 1)[1].split("\n## ", 1)[0]


def test_import_mode_precedes_phase_2():
    text = _text()
    assert "## Import Mode" in text
    assert text.index("## Import Mode") < text.index("## Phase 2: Analyze")


def test_import_mode_reads_the_prepared_timeline():
    section = _import_section()
    for marker in ("project.json", 'ext["clips"]', "frame_times", "timeline", "[File:", "600"):
        assert marker in section, marker


def test_import_mode_never_mutates_via_api():
    section = _import_section()
    assert "/api/demo-media" in section
    assert "never call" in section.lower()


def test_phase_4_mixes_the_soundtrack_through_the_merge_tool():
    section = _import_section()
    assert "soundtrack.m4a" in section and "demo_merge_narration" in section
