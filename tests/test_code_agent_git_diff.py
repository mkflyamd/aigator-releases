"""The Changes view must show the contents of untracked files, not 'No changes'."""

import asyncio
import subprocess

import pytest

from routes import code_agent


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "tracked.txt").write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-m", "init")
    import skills.code_agent.projects as projects

    monkeypatch.setattr(
        projects, "get_project", lambda name: {"name": name, "repo_path": str(tmp_path)}
    )
    return tmp_path


def _diff(file, staged=False):
    return asyncio.run(code_agent.git_diff("p", file, staged))["diff"]


def test_untracked_file_diff_shows_its_lines_as_added(repo):
    (repo / "new file.md").write_text("alpha\nbeta\n", encoding="utf-8")
    diff = _diff("new file.md")
    assert "new file mode" in diff
    assert "+alpha" in diff and "+beta" in diff


def test_untracked_file_in_subfolder(repo):
    (repo / "docs").mkdir()
    (repo / "docs" / "a.md").write_text("hello\n", encoding="utf-8")
    assert "+hello" in _diff("docs/a.md")


def test_untracked_binary_file_does_not_dump_bytes(repo):
    (repo / "blob.bin").write_bytes(b"\x00\x01\x02\xff" * 64)
    diff = _diff("blob.bin")
    assert "Binary files" in diff


def test_modified_tracked_file_diff_unchanged(repo):
    (repo / "tracked.txt").write_text("one\ntwo\n", encoding="utf-8")
    diff = _diff("tracked.txt")
    assert "+two" in diff and "new file mode" not in diff


def test_clean_tracked_file_diff_is_empty(repo):
    assert _diff("tracked.txt") == ""


def test_staged_flag_still_returns_staged_diff(repo):
    (repo / "tracked.txt").write_text("one\nstaged\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    assert "+staged" in _diff("tracked.txt", staged=True)
