import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'web'))

import pytest
from marketplace.github_fetcher import parse_github_url


def test_parse_tree_url():
    result = parse_github_url(
        "https://github.com/ComposioHQ/awesome-claude-skills/tree/master/document-skills/docx"
    )
    assert result == {
        "owner": "ComposioHQ",
        "repo": "awesome-claude-skills",
        "branch": "master",
        "path": "document-skills/docx",
        "kind": "folder",
    }


def test_parse_blob_url_to_skill_md():
    result = parse_github_url(
        "https://github.com/foo/bar/blob/main/skills/docx/SKILL.md"
    )
    assert result["kind"] == "folder"
    assert result["path"] == "skills/docx"


def test_parse_raw_skill_md_url():
    result = parse_github_url(
        "https://raw.githubusercontent.com/foo/bar/main/skills/docx/SKILL.md"
    )
    assert result == {
        "owner": "foo",
        "repo": "bar",
        "branch": "main",
        "path": "skills/docx/SKILL.md",
        "kind": "raw_file",
    }


def test_parse_rejects_non_github():
    with pytest.raises(ValueError, match="Unsupported URL"):
        parse_github_url("https://gitlab.com/foo/bar")


def test_parse_rejects_repo_root():
    with pytest.raises(ValueError, match="folder"):
        parse_github_url("https://github.com/foo/bar")


def test_parse_rejects_root_level_skill_md_blob():
    with pytest.raises(ValueError, match="root-level"):
        parse_github_url("https://github.com/foo/bar/blob/main/SKILL.md")


# ---------------------------------------------------------------------------
# download_skill_tarball tests
# ---------------------------------------------------------------------------
from unittest.mock import patch, MagicMock
import io
import tarfile

from marketplace import github_fetcher


def _make_tarball(entries: dict, symlinks: dict | None = None) -> bytes:
    """Build an in-memory tar.gz. entries: {name: bytes}. symlinks: {name: target}."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in entries.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.type = tarfile.REGTYPE
            tf.addfile(info, io.BytesIO(data))
        for name, target in (symlinks or {}).items():
            info = tarfile.TarInfo(name=name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            tf.addfile(info)
    return buf.getvalue()


def _mock_codeload_response(data: bytes, content_length=None):
    """Build a mock response object that urlopen would return."""
    resp = MagicMock()
    resp.read = MagicMock(side_effect=lambda n=None: data if n is None else data[:n])
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.headers = {"Content-Length": str(content_length)} if content_length is not None else {}
    return resp


def test_download_skill_tarball_extracts_subpath():
    tar_bytes = _make_tarball({
        "myrepo-main/skills/foo/SKILL.md": b"# foo skill\n",
        "myrepo-main/skills/foo/tools.py": b"print('foo')\n",
        "myrepo-main/skills/bar/SKILL.md": b"# bar skill\n",
        "myrepo-main/README.md": b"# repo readme\n",
    })
    resp = _mock_codeload_response(tar_bytes, content_length=len(tar_bytes))
    with patch("marketplace.github_fetcher.urllib.request.urlopen", return_value=resp):
        result = github_fetcher.download_skill_tarball("owner", "myrepo", "main", "skills/foo")
    assert set(result.keys()) == {"SKILL.md", "tools.py"}
    assert result["SKILL.md"] == b"# foo skill\n"
    assert result["tools.py"] == b"print('foo')\n"


def test_download_skill_tarball_empty_subpath_returns_root():
    tar_bytes = _make_tarball({
        "myrepo-main/SKILL.md": b"# root skill\n",
        "myrepo-main/tools.py": b"print('root')\n",
    })
    resp = _mock_codeload_response(tar_bytes, content_length=len(tar_bytes))
    with patch("marketplace.github_fetcher.urllib.request.urlopen", return_value=resp):
        result = github_fetcher.download_skill_tarball("owner", "myrepo", "main", "")
    assert set(result.keys()) == {"SKILL.md", "tools.py"}


def test_download_skill_tarball_rejects_oversized_archive_by_header():
    resp = _mock_codeload_response(b"", content_length=200 * 1024 * 1024)
    with patch("marketplace.github_fetcher.urllib.request.urlopen", return_value=resp):
        with pytest.raises(ValueError, match="archive too large"):
            github_fetcher.download_skill_tarball("o", "r", "main", "")


def test_download_skill_tarball_rejects_oversized_archive_by_stream():
    """No Content-Length header, but body exceeds the cap: stream-level guard fires."""
    oversized = b"x" * (github_fetcher.MAX_ARCHIVE_BYTES + 100)
    resp = _mock_codeload_response(oversized, content_length=None)
    with patch("marketplace.github_fetcher.urllib.request.urlopen", return_value=resp):
        with pytest.raises(ValueError, match="archive too large"):
            github_fetcher.download_skill_tarball("o", "r", "main", "")


def test_download_skill_tarball_rejects_symlink_entry():
    tar_bytes = _make_tarball(
        entries={"r-main/SKILL.md": b"x"},
        symlinks={"r-main/evil": "/etc/passwd"},
    )
    resp = _mock_codeload_response(tar_bytes, content_length=len(tar_bytes))
    with patch("marketplace.github_fetcher.urllib.request.urlopen", return_value=resp):
        with pytest.raises(ValueError, match="symlink"):
            github_fetcher.download_skill_tarball("o", "r", "main", "")


def test_download_skill_tarball_rejects_path_traversal_entry():
    tar_bytes = _make_tarball({
        "r-main/../evil.py": b"evil",
        "r-main/SKILL.md": b"ok",
    })
    resp = _mock_codeload_response(tar_bytes, content_length=len(tar_bytes))
    with patch("marketplace.github_fetcher.urllib.request.urlopen", return_value=resp):
        with pytest.raises(ValueError, match="Invalid file path"):
            github_fetcher.download_skill_tarball("o", "r", "main", "")


def test_download_skill_tarball_rejects_too_many_files():
    entries = {f"r-main/skills/foo/f{i:03d}.txt": b"x" for i in range(101)}
    entries["r-main/skills/foo/SKILL.md"] = b"# foo\n"
    tar_bytes = _make_tarball(entries)
    resp = _mock_codeload_response(tar_bytes, content_length=len(tar_bytes))
    with patch("marketplace.github_fetcher.urllib.request.urlopen", return_value=resp):
        with pytest.raises(ValueError, match="too many files"):
            github_fetcher.download_skill_tarball("o", "r", "main", "skills/foo")


def test_download_skill_tarball_rejects_total_size_over_cap():
    big = b"x" * (11 * 1024 * 1024)
    tar_bytes = _make_tarball({"r-main/SKILL.md": b"ok", "r-main/big.bin": big})
    resp = _mock_codeload_response(tar_bytes, content_length=len(tar_bytes))
    with patch("marketplace.github_fetcher.urllib.request.urlopen", return_value=resp):
        with pytest.raises(ValueError, match="too large"):
            github_fetcher.download_skill_tarball("o", "r", "main", "")
