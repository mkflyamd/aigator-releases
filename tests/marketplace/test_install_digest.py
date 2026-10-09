import io
import json
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from marketplace import installer
from marketplace.permissions import files_digest

SKILL_MD = (
    "---\nname: demo-skill\ndescription: d\n"
    "permissions:\n  filesystem: []\n  network: [api.example.com]\n---\nBody\n"
)


@pytest.fixture(autouse=True)
def _dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "INSTALLED_SKILLS_DIR", tmp_path / "skills")
    monkeypatch.setattr(installer, "PLUGINS_DIR", tmp_path / "plugins")


def _zip(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _urlopen_returning(data: bytes):
    resp = MagicMock()
    resp.read.return_value = data
    cm = MagicMock()
    cm.__enter__.return_value = resp
    cm.__exit__.return_value = False
    return MagicMock(return_value=cm)


def _index():
    return installer.load_installed()


# ── preview_package ──────────────────────────────────────────────────────────

def test_preview_inline_returns_files_and_writes_nothing():
    res = installer.preview_package(skill_md=SKILL_MD)
    assert res["ok"] is True
    assert res["files"] == {"SKILL.md": SKILL_MD.encode()}
    assert not installer.INSTALLED_SKILLS_DIR.exists()


def test_preview_local_zip_strips_the_root_folder():
    data = _zip({"demo/SKILL.md": SKILL_MD, "demo/tools.py": "TOOL_DEFS = []\n", "other/x.txt": "x"})
    res = installer.preview_package(local_zip_bytes=data)
    assert res["ok"] is True
    assert set(res["files"]) == {"SKILL.md", "tools.py"}


@pytest.mark.parametrize(
    "data, message",
    [
        (b"not a zip", "not a ZIP"),
        (_zip({"readme.txt": "x"}), "No SKILL.md"),
        (_zip({"SKILL.md": SKILL_MD, "../evil.py": "x"}), "path traversal"),
    ],
)
def test_preview_local_zip_rejects_bad_archives(data, message):
    res = installer.preview_package(local_zip_bytes=data)
    assert res["ok"] is False
    assert message in res["error"]


def test_preview_url_accepts_a_zip_and_a_raw_skill_md():
    with patch("urllib.request.urlopen", _urlopen_returning(_zip({"SKILL.md": SKILL_MD}))):
        zipped = installer.preview_package(install_url="https://example.com/s.zip")
    with patch("urllib.request.urlopen", _urlopen_returning(SKILL_MD.encode())):
        raw = installer.preview_package(install_url="https://example.com/SKILL.md")
    assert zipped["files"] == raw["files"] == {"SKILL.md": SKILL_MD.encode()}


def test_preview_url_rejects_other_schemes_and_wraps_download_errors():
    assert "http" in installer.preview_package(install_url="ftp://example.com/s")["error"]
    boom = MagicMock(side_effect=OSError("offline"))
    with patch("urllib.request.urlopen", boom):
        res = installer.preview_package(install_url="https://example.com/s")
    assert res["ok"] is False and res["error"].startswith("Download failed")


# ── install_skill_md ─────────────────────────────────────────────────────────

def test_install_with_matching_digest_writes_and_reports_permissions():
    files = installer.preview_package(skill_md=SKILL_MD)["files"]
    res = installer.install_skill_md(
        "demo-skill", SKILL_MD, "1.0", "Community", expected_digest=files_digest(files)
    )
    assert res["ok"] is True
    assert res["skill_id"] == "demo-skill"
    assert res["permissions"]["network"] == ["api.example.com"]
    assert (installer.INSTALLED_SKILLS_DIR / "demo-skill" / "SKILL.md").read_text(encoding="utf-8") == SKILL_MD
    assert [e["id"] for e in _index()] == ["demo-skill"]


def test_install_with_wrong_digest_writes_nothing():
    res = installer.install_skill_md(
        "demo-skill", SKILL_MD, "1.0", "Community", expected_digest="0" * 64
    )
    assert res == {"ok": False, "error": "content_changed"}
    assert not (installer.INSTALLED_SKILLS_DIR / "demo-skill").exists()
    assert _index() == []


def test_install_without_a_digest_still_works():
    assert installer.install_skill_md("demo-skill", SKILL_MD, "1.0", "Community")["ok"] is True


def test_install_still_rejects_an_id_that_escapes_the_skills_folder():
    res = installer.install_skill_md("../evil", SKILL_MD, "1.0", "Community")
    assert res["ok"] is False and "escapes" in res["error"]


def test_install_local_zip_derives_the_id_from_the_frontmatter_name():
    data = _zip({"folder/SKILL.md": SKILL_MD, "folder/tools.py": "TOOL_DEFS = []\n"})
    res = installer.install_skill_md("", "", "1.0", "Community", _local_zip_bytes=data)
    assert res["ok"] is True and res["skill_id"] == "demo-skill"
    assert (installer.INSTALLED_SKILLS_DIR / "demo-skill" / "tools.py").exists()
    assert _index()[0]["has_tools"] is True


def test_install_local_zip_with_root_level_skill_md_and_no_name_falls_back():
    data = _zip({"SKILL.md": "No frontmatter here\n"})
    res = installer.install_skill_md("", "", "1.0", "Community", _local_zip_bytes=data)
    assert res["ok"] is True and res["skill_id"] == "skill"


def test_install_local_zip_with_wrong_digest_writes_nothing():
    data = _zip({"SKILL.md": SKILL_MD})
    res = installer.install_skill_md(
        "", "", "1.0", "Community", _local_zip_bytes=data, expected_digest="0" * 64
    )
    assert res["error"] == "content_changed"
    assert not installer.INSTALLED_SKILLS_DIR.exists()


def test_install_url_zip_with_wrong_digest_writes_nothing():
    with patch("urllib.request.urlopen", _urlopen_returning(_zip({"SKILL.md": SKILL_MD}))):
        res = installer.install_skill_md(
            "demo-skill", "", "1.0", "Community",
            install_url="https://example.com/s.zip", expected_digest="0" * 64,
        )
    assert res["error"] == "content_changed"
    assert not (installer.INSTALLED_SKILLS_DIR / "demo-skill").exists()


# ── install_github_url ───────────────────────────────────────────────────────

GITHUB_URL = "https://github.com/octo/repo/tree/main/skills/demo"


def test_github_url_plain_skill_fetches_once_and_installs():
    files = {"SKILL.md": SKILL_MD.encode(), "notes.md": b"n"}
    with patch.object(installer.github_fetcher, "download_skill_tarball", return_value=files) as dl:
        res = installer.install_github_url(
            GITHUB_URL, "demo", expected_digest=files_digest(files)
        )
    assert dl.call_count == 1
    assert res["ok"] is True and res["permissions"]["network"] == ["api.example.com"]
    assert (installer.INSTALLED_SKILLS_DIR / "demo" / "notes.md").exists()


def test_github_url_bundle_goes_to_the_plugin_installer_with_the_same_files():
    files = {"a/SKILL.md": b"A", "b/SKILL.md": b"B"}
    with patch.object(installer.github_fetcher, "download_skill_tarball", return_value=files), \
         patch.object(installer, "install_github_url_plugin",
                      return_value={"ok": True, "plugin_id": "bundle"}) as plug:
        res = installer.install_github_url(GITHUB_URL, "bundle")
    plug.assert_called_once()
    assert plug.call_args.kwargs["_files"] is files
    assert plug.call_args.kwargs["consented"] is True
    assert res["ok"] is True and "permissions" in res


def test_github_url_wrong_digest_installs_nothing():
    files = {"SKILL.md": SKILL_MD.encode()}
    with patch.object(installer.github_fetcher, "download_skill_tarball", return_value=files), \
         patch.object(installer, "_install_github_folder") as folder:
        res = installer.install_github_url(GITHUB_URL, "demo", expected_digest="0" * 64)
    assert res == {"ok": False, "error": "content_changed"}
    folder.assert_not_called()


def test_github_url_without_skill_md_and_raw_urls_are_errors():
    with patch.object(installer.github_fetcher, "download_skill_tarball", return_value={"x.txt": b"x"}):
        assert "No SKILL.md" in installer.install_github_url(GITHUB_URL, "demo")["error"]
    raw = "https://raw.githubusercontent.com/octo/repo/main/SKILL.md"
    assert "install_skill_md" in installer.install_github_url(raw, "demo")["error"]


def test_folder_installer_with_files_does_not_fetch():
    files = {"SKILL.md": SKILL_MD.encode()}
    with patch.object(installer.github_fetcher, "download_skill_tarball") as dl:
        res = installer._install_github_folder(GITHUB_URL, "demo", _files=files)
    dl.assert_not_called()
    assert res["ok"] is True


# ── capabilities carry the fetched package ───────────────────────────────────

def test_github_capabilities_return_the_package():
    files = {"SKILL.md": SKILL_MD.encode()}
    with patch.object(installer.github_fetcher, "download_skill_tarball", return_value=files):
        caps = installer.get_github_url_capabilities(GITHUB_URL)
    assert caps["ok"] is True and caps["package"] == files


def test_catalog_capabilities_return_the_package_and_install_checks_the_digest():
    files = {"skills/x/SKILL.md": SKILL_MD.encode(), "plugin.json": json.dumps({"version": "1.2"}).encode()}
    entry = {"id": "cat-plugin", "plugin_source": {"url": "https://github.com/o/r.git"}}
    with patch.object(installer, "_fetch_plugin_source_tree", return_value=("cat-plugin", files, "abc")):
        caps = installer.get_claude_plugins_official_capabilities(entry)
        assert caps["package"] == files
        bad = installer.install_claude_plugins_official_plugin(
            entry, consented=True, pinned_ref="abc", expected_digest="0" * 64
        )
    assert bad == {"ok": False, "error": "content_changed"}
    assert not (installer.PLUGINS_DIR / "cache").exists()
