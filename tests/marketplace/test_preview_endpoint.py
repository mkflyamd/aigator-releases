import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'web'))

from unittest.mock import patch
from fastapi.testclient import TestClient
from fastapi import FastAPI
from routes.marketplace import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_preview_returns_manifest(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "INSTALLED_SKILLS_DIR", tmp_path)
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    parsed = {"owner": "f", "repo": "b", "branch": "m", "path": "skills/docx", "kind": "folder"}
    files = {
        "SKILL.md": b"---\nname: docx\ndescription: edit Word\n---\n",
        "tools.py": b"x" * 200,
    }
    with patch("marketplace.github_fetcher.parse_github_url", return_value=parsed), \
         patch("marketplace.github_fetcher.download_skill_tarball", return_value=files):
        r = _client().post("/api/marketplace/preview",
                           json={"url": "https://github.com/f/b/tree/m/skills/docx"})
    assert r.status_code == 200
    body = r.json()
    assert body["skill_id"] == "docx"
    assert body["name"] == "docx"
    assert body["description"] == "edit Word"
    assert body["total_size"] == len(files["SKILL.md"]) + 200
    assert {"path": "SKILL.md", "size": len(files["SKILL.md"])} in body["files"]
    assert {"path": "tools.py", "size": 200} in body["files"]
    assert body["existing_files"] == []
    assert body["orphans"] == []


def test_preview_rejects_bad_url():
    r = _client().post("/api/marketplace/preview",
                       json={"url": "https://gitlab.com/foo/bar"})
    assert r.status_code == 400
    assert "Unsupported URL" in r.json()["detail"]


def test_preview_reports_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    import config
    monkeypatch.setattr(config, "INSTALLED_SKILLS_DIR", tmp_path)
    import marketplace.installer as m, importlib; importlib.reload(m)
    m.install_skill_md("docx", "---\nname: docx\n---\n", "1.0", "Community")
    parsed = {"owner": "f", "repo": "b", "branch": "m", "path": "docx", "kind": "folder"}
    files = {"SKILL.md": b"---\nname: docx\n---\n"}
    with patch("marketplace.github_fetcher.parse_github_url", return_value=parsed), \
         patch("marketplace.github_fetcher.download_skill_tarball", return_value=files):
        r = _client().post("/api/marketplace/preview",
                           json={"url": "https://github.com/f/b/tree/m/docx"})
    assert r.status_code == 200
    assert "overwrite" in r.json()["warnings"]


def test_install_routes_github_url_to_folder_installer(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    import marketplace.installer as m, importlib; importlib.reload(m)
    with patch("marketplace.installer._install_github_folder",
               return_value={"ok": True, "skill_id": "docx"}) as fake_inst:
        r = _client().post("/api/marketplace/install", json={
            "skill_id": "docx",
            "install_url": "https://github.com/foo/bar/tree/main/skills/docx",
            "tier": "Verified",  # should be ignored — forced to Community
        })
    assert r.status_code == 200
    fake_inst.assert_called_once()
    args, _ = fake_inst.call_args
    assert args[0] == "https://github.com/foo/bar/tree/main/skills/docx"
    assert args[1] == "docx"


def test_preview_rejects_missing_skill_md():
    """Tarball without a SKILL.md at top level should be rejected."""
    parsed = {"owner": "f", "repo": "b", "branch": "m", "path": "skills/docx", "kind": "folder"}
    files = {"README.md": b"hi"}
    with patch("marketplace.github_fetcher.parse_github_url", return_value=parsed), \
         patch("marketplace.github_fetcher.download_skill_tarball", return_value=files):
        r = _client().post("/api/marketplace/preview",
                           json={"url": "https://github.com/f/b/tree/m/skills/docx"})
    assert r.status_code == 400
    assert "SKILL.md" in r.json()["detail"]


def test_preview_returns_files_and_orphans_for_reinstall(monkeypatch, tmp_path):
    """Preview of a re-import returns existing_files and orphans diff."""
    import marketplace.installer as inst
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)
    import config
    monkeypatch.setattr(config, "INSTALLED_SKILLS_DIR", tmp_path)

    skill_dir = tmp_path / "foo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: foo\n---\n")
    (skill_dir / "helpers.py").write_text("old")
    from marketplace.installer import save_installed
    save_installed([{"id": "foo", "version": "1.0", "tier": "Community"}])

    fake = {"SKILL.md": b"---\nname: foo\n---\n", "tools.py": b"new"}
    import marketplace.github_fetcher as gf
    monkeypatch.setattr(gf, "download_skill_tarball", lambda *a, **kw: fake)

    resp = _client().post("/api/marketplace/preview", json={
        "url": "https://github.com/owner/repo/tree/main/skills/foo"
    })
    body = resp.json()
    assert resp.status_code == 200
    assert sorted(body["existing_files"]) == ["SKILL.md", "helpers.py"]
    assert body["orphans"] == ["helpers.py"]


def test_install_passes_orphan_resolution_to_installer(monkeypatch, tmp_path):
    import marketplace.installer as inst
    captured = {}

    def fake_install(install_url, skill_id, version="1.0", orphan_resolution=None):
        captured["orphan_resolution"] = orphan_resolution
        return {"ok": True, "skill_id": skill_id}

    monkeypatch.setattr(inst, "_install_github_folder", fake_install)

    resp = _client().post("/api/marketplace/install", json={
        "skill_id": "foo",
        "install_url": "https://github.com/owner/repo/tree/main/skills/foo",
        "orphan_resolution": "delete",
    })
    assert resp.status_code == 200
    assert captured["orphan_resolution"] == "delete"


def test_install_returns_400_with_orphans_when_no_resolution(monkeypatch, tmp_path):
    import marketplace.installer as inst

    def fake_install(*a, **kw):
        return {"ok": False, "error": "orphan_resolution_required",
                "orphans": ["helpers.py"]}

    monkeypatch.setattr(inst, "_install_github_folder", fake_install)

    resp = _client().post("/api/marketplace/install", json={
        "skill_id": "foo",
        "install_url": "https://github.com/owner/repo/tree/main/skills/foo",
    })
    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"]["error"] == "Orphan files require resolution"
    assert body["detail"]["orphans"] == ["helpers.py"]


def test_preview_first_install_has_empty_orphans(monkeypatch, tmp_path):
    import marketplace.installer as inst
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)
    import config
    monkeypatch.setattr(config, "INSTALLED_SKILLS_DIR", tmp_path)
    fake = {"SKILL.md": b"---\nname: foo\n---\n"}
    import marketplace.github_fetcher as gf
    monkeypatch.setattr(gf, "download_skill_tarball", lambda *a, **kw: fake)
    resp = _client().post("/api/marketplace/preview", json={
        "url": "https://github.com/owner/repo/tree/main/skills/foo"
    })
    body = resp.json()
    assert body["existing_files"] == []
    assert body["orphans"] == []
