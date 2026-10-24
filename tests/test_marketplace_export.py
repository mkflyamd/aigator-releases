import io
import pathlib
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest
from fastapi.testclient import TestClient

import config
import routes.marketplace as marketplace_routes
from app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mine_skill(tmp_path, monkeypatch):
    skill_dir = tmp_path / "mine" / "weekly-recap"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: Weekly recap\n---\nSteps", encoding="utf-8")
    (skill_dir / "references" / "notes.md").write_text("notes", encoding="utf-8")
    monkeypatch.setattr(config, "INSTALLED_SKILLS_DIR", tmp_path)
    monkeypatch.setattr(
        marketplace_routes,
        "load_installed",
        lambda: [
            {"id": "weekly-recap", "tier": "Mine"},
            {"id": "other", "tier": "Community"},
        ],
    )
    return skill_dir


def test_export_returns_a_skill_zip_with_skill_md_at_the_top(client, mine_skill):
    resp = client.get("/api/marketplace/export/weekly-recap")
    assert resp.status_code == 200
    assert resp.content[:4] == b"PK\x03\x04"
    assert 'filename="weekly-recap.skill"' in resp.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        assert sorted(zf.namelist()) == ["SKILL.md", "references/notes.md"]
        assert zf.read("SKILL.md").decode("utf-8").endswith("Steps")


def test_export_refuses_a_skill_that_is_not_mine(client, mine_skill):
    assert client.get("/api/marketplace/export/other").status_code == 403


def test_export_unknown_skill_is_404(client, mine_skill):
    assert client.get("/api/marketplace/export/missing").status_code == 404
