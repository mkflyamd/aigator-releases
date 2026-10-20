from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "web" / "skills" / "gator-demo-recorder" / "SKILL.md"
TEXT = SKILL.read_text(encoding="utf-8")
TOOLS = ("demo_media_manifest", "demo_inspect_frames", "demo_replace_interval",
         "demo_append_clip", "demo_merge_narration")
MERGE_ERRORS = ("approval_superseded", "narration_not_approved", "approval_corrupt", "approval_stale_media",
                "out_of_range", "sync_mismatch", "output_verification_failed", "tts_failed")


def _between(start: str, end: str) -> str:
    i = TEXT.index(start)
    return TEXT[i:TEXT.index(end, i)]


def test_truthful_media_claims_section_names_every_tool_and_result_field():
    section = _between("## Truthful Media Claims", "## Phase 1")
    for name in TOOLS:
        assert name in section
    for field in ("inserted_from", "appended_from", "video_extended_by_sec", "out_of_range"):
        assert field in section


def test_phase2_points_to_frame_inspection():
    assert "demo_inspect_frames" in _between("## Phase 2: Analyze", "## Phase 3")


def test_phase4_merges_through_the_tool_not_inline_code():
    phase4 = _between("## Phase 4: TTS + Merge", "## Phase 5: Deliver")
    assert "demo_merge_narration" in phase4
    assert "```python" not in phase4
    assert "subprocess" not in phase4
    assert '"Hold" freezes the first frame' in phase4 and '"Title card"' in phase4
    for code in MERGE_ERRORS:
        assert f"`{code}`" in phase4


def test_phase5_reports_only_merge_result_facts():
    phase5 = TEXT[TEXT.index("## Phase 5: Deliver"):]
    assert "`demo_merge_narration` result" in phase5
