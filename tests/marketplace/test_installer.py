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
