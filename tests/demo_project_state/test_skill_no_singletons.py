from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "web" / "skills" / "gator-demo-recorder"
FORBIDDEN = ("latest-output", "set-output", "latest_output.json", "narration_pending.json", "gator_demos")


def test_skill_has_no_singleton_or_hardcoded_root_references():
    offenders = []
    for f in [SKILL / "SKILL.md", *(SKILL / "scripts").glob("*.py")]:
        text = f.read_text(encoding="utf-8")
        offenders += [f"{f.name}: {needle}" for needle in FORBIDDEN if needle in text]
    assert offenders == []


def test_skill_documents_project_folder_resolver():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "demo_projects.json" in text and "PROJECT_DIR" in text
    assert "work/narration.json" in text and "final/" in text
