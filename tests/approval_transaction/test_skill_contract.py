import re
from pathlib import Path

SKILL = (
    Path(__file__).resolve().parents[2] / "web" / "skills" / "gator-demo-recorder" / "SKILL.md"
).read_text(encoding="utf-8")


def test_every_widget_send_is_pinned():
    sends = [m.start() for m in re.finditer(r"type:'gator:send-message'", SKILL)]
    assert len(sends) >= 4
    for start in sends:
        assert "pin_skill:'gator-demo-recorder'" in SKILL[start : start + 260], SKILL[start : start + 120]


def test_recording_complete_send_carries_project_id():
    i = SKILL.index("'Recording complete. File: '")
    assert "project_id:(data&&data.project_id)||''" in SKILL[i : i + 600]


def test_phase3_widget_posts_through_guarded_approve():
    assert "PROJECT_ID_PLACEHOLDER" in SKILL
    assert 'id="btn-approve"' in SKILL
    assert "_approving" in SKILL
    assert "gator:narration-approval-result" in SKILL
    assert "/^demo_\\d/" in SKILL
    assert "' PROJECT_ID:'" in SKILL


def test_phase4_merges_through_the_verifying_tool():
    assert "demo_merge_narration" in SKILL
    assert "approval appr_<n>_<hash>" in SKILL
    assert "approval (appr_\\d+_[0-9a-f]{8})" in SKILL
    for code in ("approval_superseded", "narration_not_approved", "approval_corrupt", "approval_stale_media"):
        assert f"`{code}`" in SKILL
