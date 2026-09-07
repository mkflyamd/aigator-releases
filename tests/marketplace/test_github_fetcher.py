import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "web"))

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
    resp.headers = (
        {"Content-Length": str(content_length)} if content_length is not None else {}
    )
    return resp


def test_download_skill_tarball_extracts_subpath():
    tar_bytes = _make_tarball(
        {
            "myrepo-main/skills/foo/SKILL.md": b"# foo skill\n",
            "myrepo-main/skills/foo/tools.py": b"print('foo')\n",
            "myrepo-main/skills/bar/SKILL.md": b"# bar skill\n",
            "myrepo-main/README.md": b"# repo readme\n",
        }
    )
    resp = _mock_codeload_response(tar_bytes, content_length=len(tar_bytes))
    with patch("marketplace.github_fetcher.urllib.request.urlopen", return_value=resp):
        result = github_fetcher.download_skill_tarball(
            "owner", "myrepo", "main", "skills/foo"
        )
    assert set(result.keys()) == {"SKILL.md", "tools.py"}
    assert result["SKILL.md"] == b"# foo skill\n"
    assert result["tools.py"] == b"print('foo')\n"


def test_download_skill_tarball_empty_subpath_returns_root():
    tar_bytes = _make_tarball(
        {
            "myrepo-main/SKILL.md": b"# root skill\n",
            "myrepo-main/tools.py": b"print('root')\n",
        }
    )
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
    tar_bytes = _make_tarball(
        {
            "r-main/../evil.py": b"evil",
            "r-main/SKILL.md": b"ok",
        }
    )
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


# ---------------------------------------------------------------------------
# P0 — archive-root normalization (renamed-repository case)
# ---------------------------------------------------------------------------
# GitHub's codeload service names the top-level directory after the CURRENT
# repository name, not the name used in the request URL.  After a rename
# (e.g. slack-mcp-plugin → slack-skills-plugin), the archive root becomes
# "slack-skills-plugin-{sha}/" even though the request URL still says
# "slack-mcp-plugin".  The fix derives the actual root from the tarball via
# _detect_archive_root() instead of hardcoding "{repo}-{branch}/".


def test_detect_archive_root_returns_actual_root():
    """_detect_archive_root finds the real root directory from tarball contents."""
    tar_bytes = _make_tarball(
        {
            "slack-skills-plugin-abc123/SKILL.md": b"# slack\n",
            "slack-skills-plugin-abc123/tools.py": b"print('slack')\n",
        }
    )
    buf = io.BytesIO(tar_bytes)
    with tarfile.open(fileobj=buf, mode="r:gz") as tf:
        root = github_fetcher._detect_archive_root(tf)
    assert root == "slack-skills-plugin-abc123/"


def test_detect_archive_root_rejects_multi_root_archive():
    """An archive with multiple top-level directories is rejected as anomalous."""
    tar_bytes = _make_tarball(
        {
            "rootA/SKILL.md": b"# a\n",
            "rootB/SKILL.md": b"# b\n",
        }
    )
    buf = io.BytesIO(tar_bytes)
    with tarfile.open(fileobj=buf, mode="r:gz") as tf:
        with pytest.raises(ValueError, match="multiple top-level"):
            github_fetcher._detect_archive_root(tf)


def test_download_skill_tarball_renamed_repo_slack_case():
    """The Slack renamed-repository case: request repo='slack-mcp-plugin' but
    the archive root is 'slack-skills-plugin-{sha}/' — should extract correctly."""
    sha = "deadbeefcafe1234"  # pragma: allowlist secret
    tar_bytes = _make_tarball(
        {
            f"slack-skills-plugin-{sha}/SKILL.md": b"# Slack skill\n",
            f"slack-skills-plugin-{sha}/tools.py": b"# Slack tools\n",
            f"slack-skills-plugin-{sha}/.mcp.json": b'{"mcpServers":{}}',
            f"slack-skills-plugin-{sha}/README.md": b"# readme\n",
        }
    )
    resp = _mock_codeload_response(tar_bytes, content_length=len(tar_bytes))
    with patch("marketplace.github_fetcher.urllib.request.urlopen", return_value=resp):
        result = github_fetcher.download_skill_tarball(
            "anthropics", "slack-mcp-plugin", sha, ""
        )
    assert "SKILL.md" in result
    assert result["SKILL.md"] == b"# Slack skill\n"
    assert "tools.py" in result
    assert ".mcp.json" in result


def test_download_skill_tarball_renamed_repo_with_subpath():
    """Renamed-repository case with a subpath — the subpath is resolved relative
    to the detected (renamed) archive root, not the requested repo name."""
    sha = "abc123def456"  # pragma: allowlist secret
    tar_bytes = _make_tarball(
        {
            f"new-repo-name-{sha}/plugins/slack/SKILL.md": b"# slack plugin\n",
            f"new-repo-name-{sha}/plugins/slack/.mcp.json": b'{"mcpServers":{}}',
            f"new-repo-name-{sha}/plugins/other/SKILL.md": b"# other\n",
            f"new-repo-name-{sha}/README.md": b"# readme\n",
        }
    )
    resp = _mock_codeload_response(tar_bytes, content_length=len(tar_bytes))
    with patch("marketplace.github_fetcher.urllib.request.urlopen", return_value=resp):
        result = github_fetcher.download_skill_tarball(
            "owner", "old-repo-name", sha, "plugins/slack"
        )
    assert set(result.keys()) == {"SKILL.md", ".mcp.json"}
    assert result["SKILL.md"] == b"# slack plugin\n"


def test_download_skill_tarball_symlink_outside_selected_subtree_skipped():
    """A symlink in the archive OUTSIDE the selected plugin subtree is skipped
    silently — it is never extracted or followed.  The selected subtree is
    returned without error."""
    tar_bytes = _make_tarball(
        entries={
            "repo-main/plugins/slack/SKILL.md": b"# slack\n",
            "repo-main/plugins/slack/tools.py": b"# tools\n",
            "repo-main/README.md": b"# readme\n",
        },
        symlinks={
            "repo-main/outside-symlink": "/etc/passwd",
        },
    )
    resp = _mock_codeload_response(tar_bytes, content_length=len(tar_bytes))
    with patch("marketplace.github_fetcher.urllib.request.urlopen", return_value=resp):
        result = github_fetcher.download_skill_tarball(
            "owner", "repo", "main", "plugins/slack"
        )
    assert set(result.keys()) == {"SKILL.md", "tools.py"}


def test_download_skill_tarball_symlink_inside_selected_subtree_rejected():
    """A symlink INSIDE the selected plugin subtree is rejected (P0 security
    requirement: reject symlinks inside the selected subtree)."""
    tar_bytes = _make_tarball(
        entries={"repo-main/plugins/slack/SKILL.md": b"# slack\n"},
        symlinks={"repo-main/plugins/slack/evil": "/etc/passwd"},
    )
    resp = _mock_codeload_response(tar_bytes, content_length=len(tar_bytes))
    with patch("marketplace.github_fetcher.urllib.request.urlopen", return_value=resp):
        with pytest.raises(ValueError, match="symlink"):
            github_fetcher.download_skill_tarball(
                "owner", "repo", "main", "plugins/slack"
            )


def test_download_skill_tarball_empty_archive_rejected():
    """An archive with no recognizable directory structure raises ValueError."""
    tar_bytes = _make_tarball({})
    resp = _mock_codeload_response(tar_bytes, content_length=len(tar_bytes))
    with patch("marketplace.github_fetcher.urllib.request.urlopen", return_value=resp):
        with pytest.raises(ValueError, match="empty"):
            github_fetcher.download_skill_tarball("o", "r", "main", "")


def test_download_skill_tarball_symlink_in_dotfile_dir_skipped():
    """A symlink inside a dotfile directory (.cursor/, .git/, etc.) is silently
    skipped — it is not a security threat because the directory is never
    extracted. This is the Canva case: canva ships a symlink at
    .cursor/skills inside its plugin archive. The real files (SKILL.md,
    .mcp.json) must still be extracted correctly."""
    tar_bytes = _make_tarball(
        entries={
            "canva-abc123/SKILL.md": b"# Canva\n",
            "canva-abc123/.mcp.json": b'{"mcpServers":{}}',
            "canva-abc123/README.md": b"# readme\n",
        },
        symlinks={
            "canva-abc123/.cursor/skills": "../skills",
        },
    )
    resp = _mock_codeload_response(tar_bytes, content_length=len(tar_bytes))
    with patch("marketplace.github_fetcher.urllib.request.urlopen", return_value=resp):
        result = github_fetcher.download_skill_tarball("canva", "canva-plugin", "abc123", "")
    # Real content extracted
    assert "SKILL.md" in result
    assert ".mcp.json" in result
    # Dotfile directory entry skipped entirely (not in output)
    assert not any(".cursor" in k for k in result)


def test_download_skill_tarball_symlink_in_nondotfile_dir_still_rejected():
    """A symlink in a regular (non-dotfile) directory inside the selected
    subtree is still rejected — the dotfile exception only applies to
    directories whose names start with '.'."""
    tar_bytes = _make_tarball(
        entries={"repo-main/SKILL.md": b"# skill\n"},
        symlinks={"repo-main/scripts/evil": "/etc/passwd"},
    )
    resp = _mock_codeload_response(tar_bytes, content_length=len(tar_bytes))
    with patch("marketplace.github_fetcher.urllib.request.urlopen", return_value=resp):
        with pytest.raises(ValueError, match="symlink"):
            github_fetcher.download_skill_tarball("o", "r", "main", "")
