import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
WEB = ROOT / "web"

sys.path.insert(0, str(ROOT / "packaging"))
from skill_imports import skill_imported_web_modules  # noqa: E402


def test_scanner_finds_modules_only_skills_import():
    found = skill_imported_web_modules(WEB)
    assert "demo_media" in found
    assert "sandbox.policy" in found


def test_every_scanned_module_exists_in_web():
    for name in skill_imported_web_modules(WEB):
        base = WEB.joinpath(*name.split("."))
        assert base.with_suffix(".py").is_file() or (base / "__init__.py").is_file(), name


def test_spec_adds_skill_imports_to_hiddenimports():
    spec = (ROOT / "packaging" / "aigator-backend.spec").read_text(encoding="utf-8")
    assert "hiddenimports += sorted(skill_imported_web_modules(web))" in spec


def test_release_smoke_fails_on_skill_import_errors():
    workflow = (ROOT / ".github" / "workflows" / "release-desktop.yml").read_text(encoding="utf-8")
    assert 'health["failed_skills"]' in workflow
