import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'web'))

def test_load_installed_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    from marketplace.installer import load_installed
    assert load_installed() == []

def test_save_and_load_installed(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    from marketplace.installer import save_installed, load_installed
    entry = {"id": "test-skill", "version": "1.0", "tier": "Community",
             "installed_at": "2026-05-15T00:00:00Z", "has_tools": False}
    save_installed([entry])
    result = load_installed()
    assert len(result) == 1
    assert result[0]["id"] == "test-skill"

import importlib

def test_install_skill_md_creates_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    import marketplace.installer as m; importlib.reload(m)
    skill_md = "---\nname: test\ndescription: A test\n---\n# Test\nDo stuff."
    result = m.install_skill_md("test-skill", skill_md, "1.0.0", "Community")
    assert result["ok"] is True
    assert (tmp_path / "test-skill" / "SKILL.md").exists()
    assert any(e["id"] == "test-skill" for e in m.load_installed())

def test_uninstall_removes_dir_and_entry(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    import marketplace.installer as m; importlib.reload(m)
    m.install_skill_md("to-remove", "---\nname: x\n---\ncontent", "1.0", "Community")
    result = m.uninstall_skill("to-remove")
    assert result["ok"] is True
    assert not (tmp_path / "to-remove").exists()
    assert not any(e["id"] == "to-remove" for e in m.load_installed())

def test_uninstall_unknown_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    import marketplace.installer as m; importlib.reload(m)
    result = m.uninstall_skill("does-not-exist")
    assert result["ok"] is False
    assert "not found" in result["error"]

def test_create_user_skill(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    import marketplace.installer as m; importlib.reload(m)
    result = m.create_user_skill("My Workflow", "Test", "Do X")
    assert result["ok"] is True
    assert result["skill_id"] == "my-workflow"
    assert (tmp_path / "mine" / "my-workflow" / "SKILL.md").exists()

def test_create_sanitizes_name(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    import marketplace.installer as m; importlib.reload(m)
    result = m.create_user_skill("My  Complex Name!", "d", "i")
    assert result["skill_id"] == "my-complex-name"

import io, zipfile
from unittest.mock import patch, MagicMock

def _make_gator_zip(skill_md_content: str) -> bytes:
    """Create an in-memory .gator ZIP with a SKILL.md file."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", skill_md_content)
    return buf.getvalue()

def test_install_skill_md_from_url(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    import marketplace.installer as m; importlib.reload(m)
    zip_bytes = _make_gator_zip("---\nname: remote\n---\n# Remote Skill")
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read = MagicMock(return_value=zip_bytes)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = m.install_skill_md("remote-skill", "", "2.0.0", "Verified",
                                     install_url="https://example.com/remote.gator")
    assert result["ok"] is True
    assert (tmp_path / "remote-skill" / "SKILL.md").exists()

def test_install_skill_md_url_missing_skill_md(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    import marketplace.installer as m; importlib.reload(m)
    # ZIP with no SKILL.md
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("tools.py", "# no skill md")
    zip_bytes = buf.getvalue()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read = MagicMock(return_value=zip_bytes)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = m.install_skill_md("bad-pkg", "", "1.0", "Community",
                                     install_url="https://example.com/bad.gator")
    assert result["ok"] is False
    assert "SKILL.md" in result["error"]

def test_install_skill_md_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    import marketplace.installer as m; importlib.reload(m)
    result = m.install_skill_md("../../escape", "---\nname: x\n---\ncontent", "1.0", "Community")
    assert result["ok"] is False
    assert "escape" in result["error"].lower() or "escapes" in result["error"].lower()
    # Verify no file was written outside tmp_path
    assert not (tmp_path.parent / "escape").exists()

def test_install_skill_md_rejects_file_url(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    import marketplace.installer as m; importlib.reload(m)
    result = m.install_skill_md("bad", "", "1.0", "Community",
                                 install_url="file:///etc/passwd")
    assert result["ok"] is False
    assert "http" in result["error"].lower()

def test_create_sanitizes_yaml_injection(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    import marketplace.installer as m; importlib.reload(m)
    result = m.create_user_skill("Skill\nmalicious: true", "desc", "instructions")
    assert result["ok"] is True
    skill_md = (tmp_path / "mine" / result["skill_id"] / "SKILL.md").read_text()
    # The newline was stripped, so "malicious: true" must appear only as part of
    # the name value on a single line — never as a standalone YAML key.
    # A standalone injected key would appear as "^malicious: true" on its own line.
    import re
    assert not re.search(r"^malicious:\s", skill_md, re.MULTILINE)


def test_install_github_folder_uses_tarball(monkeypatch, tmp_path):
    import marketplace.installer as inst
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)

    fake_tarball = {
        "SKILL.md": b"# foo\n",
        "tools.py": b"print('foo')\n",
    }
    monkeypatch.setattr(
        inst.github_fetcher,
        "download_skill_tarball",
        lambda owner, repo, branch, subpath: fake_tarball,
    )

    result = inst._install_github_folder(
        "https://github.com/owner/repo/tree/main/skills/foo", "foo", "1.0"
    )
    assert result["ok"] is True
    assert (tmp_path / "foo" / "SKILL.md").read_bytes() == b"# foo\n"
    assert (tmp_path / "foo" / "tools.py").read_bytes() == b"print('foo')\n"


def test_install_github_folder_rejects_when_no_skill_md(monkeypatch, tmp_path):
    import marketplace.installer as inst
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)
    monkeypatch.setattr(
        inst.github_fetcher,
        "download_skill_tarball",
        lambda *a, **kw: {"tools.py": b"x"},
    )
    result = inst._install_github_folder(
        "https://github.com/owner/repo/tree/main/skills/foo", "foo"
    )
    assert result["ok"] is False
    assert "SKILL.md" in result["error"]


def test_install_github_folder_returns_orphans_when_no_resolution(monkeypatch, tmp_path):
    import marketplace.installer as inst
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)
    skill_dir = tmp_path / "foo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("old")
    (skill_dir / "helpers.py").write_text("old helper")
    monkeypatch.setattr(
        inst.github_fetcher,
        "download_skill_tarball",
        lambda *a, **kw: {"SKILL.md": b"new", "tools.py": b"new"},
    )
    result = inst._install_github_folder(
        "https://github.com/owner/repo/tree/main/skills/foo", "foo"
    )
    assert result["ok"] is False
    assert result["error"] == "orphan_resolution_required"
    assert result["orphans"] == ["helpers.py"]
    # Disk untouched
    assert (skill_dir / "SKILL.md").read_text() == "old"
    assert (skill_dir / "helpers.py").exists()


def test_install_github_folder_keeps_orphans_when_resolution_keep(monkeypatch, tmp_path):
    import marketplace.installer as inst
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)
    skill_dir = tmp_path / "foo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("old")
    (skill_dir / "helpers.py").write_text("old helper")
    monkeypatch.setattr(
        inst.github_fetcher,
        "download_skill_tarball",
        lambda *a, **kw: {"SKILL.md": b"new"},
    )
    result = inst._install_github_folder(
        "https://github.com/owner/repo/tree/main/skills/foo", "foo",
        orphan_resolution="keep",
    )
    assert result["ok"] is True
    assert (skill_dir / "SKILL.md").read_text() == "new"
    assert (skill_dir / "helpers.py").exists()


def test_install_github_folder_deletes_orphans_when_resolution_delete(monkeypatch, tmp_path):
    import marketplace.installer as inst
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)
    skill_dir = tmp_path / "foo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("old")
    (skill_dir / "helpers.py").write_text("old helper")
    monkeypatch.setattr(
        inst.github_fetcher,
        "download_skill_tarball",
        lambda *a, **kw: {"SKILL.md": b"new"},
    )
    result = inst._install_github_folder(
        "https://github.com/owner/repo/tree/main/skills/foo", "foo",
        orphan_resolution="delete",
    )
    assert result["ok"] is True
    assert (skill_dir / "SKILL.md").read_text() == "new"
    assert not (skill_dir / "helpers.py").exists()


def test_install_github_folder_first_install_has_no_orphans(monkeypatch, tmp_path):
    import marketplace.installer as inst
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)
    monkeypatch.setattr(
        inst.github_fetcher,
        "download_skill_tarball",
        lambda *a, **kw: {"SKILL.md": b"new"},
    )
    result = inst._install_github_folder(
        "https://github.com/owner/repo/tree/main/skills/foo", "foo"
    )
    assert result["ok"] is True
    assert (tmp_path / "foo" / "SKILL.md").read_bytes() == b"new"


def test_install_skill_md_zip_extracts_all_files(tmp_path, monkeypatch, httpserver):
    """ZIP install must preserve tools.py and scripts/, not just SKILL.md."""
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    import marketplace.installer as m; importlib.reload(m)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("docx/SKILL.md", "---\nname: docx\n---\n# Docx")
        zf.writestr("docx/tools.py", "# tools")
        zf.writestr("docx/scripts/pack.py", "# pack")
    httpserver.expect_request("/skill.zip").respond_with_data(
        buf.getvalue(), content_type="application/zip"
    )
    url = httpserver.url_for("/skill.zip")
    result = m.install_skill_md("docx", "", "1.0", "Community", install_url=url)
    assert result["ok"] is True
    assert (tmp_path / "docx" / "SKILL.md").exists()
    assert (tmp_path / "docx" / "tools.py").exists()
    assert (tmp_path / "docx" / "scripts" / "pack.py").exists()
    entry = next(e for e in m.load_installed() if e["id"] == "docx")
    assert entry["has_tools"] is True


def test_install_zip_rejects_path_traversal(tmp_path, monkeypatch, httpserver):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    import marketplace.installer as m; importlib.reload(m)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.py", "x")
        zf.writestr("docx/SKILL.md", "---\nname: x\n---\n")
    httpserver.expect_request("/evil.zip").respond_with_data(
        buf.getvalue(), content_type="application/zip"
    )
    url = httpserver.url_for("/evil.zip")
    result = m.install_skill_md("docx", "", "1.0", "Community", install_url=url)
    assert result["ok"] is False
    assert "path traversal" in result["error"].lower()


def test_delete_orphans_removes_listed_files(tmp_path):
    from marketplace.installer import delete_orphans
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("ok")
    (skill_dir / "helpers.py").write_text("evil")
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "old.py").write_text("evil")
    delete_orphans(skill_dir, ["helpers.py", "scripts/old.py"])
    assert (skill_dir / "SKILL.md").exists()
    assert not (skill_dir / "helpers.py").exists()
    assert not (skill_dir / "scripts" / "old.py").exists()


def test_delete_orphans_prunes_now_empty_subdirs(tmp_path):
    from marketplace.installer import delete_orphans
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("ok")
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "old.py").write_text("evil")
    delete_orphans(skill_dir, ["scripts/old.py"])
    assert not (skill_dir / "scripts").exists()
    assert skill_dir.exists()


def test_delete_orphans_keeps_nonempty_subdirs(tmp_path):
    from marketplace.installer import delete_orphans
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "old.py").write_text("evil")
    (skill_dir / "scripts" / "keep.py").write_text("ok")
    delete_orphans(skill_dir, ["scripts/old.py"])
    assert (skill_dir / "scripts").exists()
    assert (skill_dir / "scripts" / "keep.py").exists()


def test_delete_orphans_rejects_path_traversal(tmp_path):
    from marketplace.installer import delete_orphans
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    sibling = tmp_path / "sibling.txt"
    sibling.write_text("must remain")
    delete_orphans(skill_dir, ["../sibling.txt"])
    assert sibling.exists()


def test_delete_orphans_never_removes_skill_dir(tmp_path):
    from marketplace.installer import delete_orphans
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "only.txt").write_text("x")
    delete_orphans(skill_dir, ["only.txt"])
    assert skill_dir.exists()
