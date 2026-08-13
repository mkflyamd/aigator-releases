"""Tests for web/skills/code_agent/projects.py — Phase 6."""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest


def _patch_dirs(projects_mod, tmp_path):
    """Redirect GATOR_HOME, PROJECTS_DIR, CONFIG_FILE to tmp_path."""
    gator_home = tmp_path / ".gator"
    projects_mod.GATOR_HOME = gator_home
    projects_mod.PROJECTS_DIR = gator_home / "projects"
    projects_mod.CONFIG_FILE = gator_home / "config.json"


class TestAddProject:
    def test_add_project_creates_dir(self, tmp_path):
        """add_project creates ~/.gator/projects/<name>/."""
        from web.skills.code_agent import projects as proj_mod

        _patch_dirs(proj_mod, tmp_path)

        # Create a fake local git repo
        fake_repo = tmp_path / "my-repo"
        fake_repo.mkdir()
        (fake_repo / ".git").mkdir()
        # git status check — mock by making it a real git repo
        import subprocess

        subprocess.run(["git", "init", str(fake_repo)], capture_output=True)

        proj_mod.add_project("my-repo", str(fake_repo), source="local")
        assert (proj_mod.PROJECTS_DIR / "my-repo").exists()

    def test_add_project_saves_to_config(self, tmp_path):
        """add_project writes project to config.json."""
        from web.skills.code_agent import projects as proj_mod

        _patch_dirs(proj_mod, tmp_path)

        fake_repo = tmp_path / "test-app"
        fake_repo.mkdir()
        import subprocess

        subprocess.run(["git", "init", str(fake_repo)], capture_output=True)

        proj_mod.add_project("test-app", str(fake_repo), source="local")
        cfg = json.loads(proj_mod.CONFIG_FILE.read_text())
        assert "test-app" in cfg["projects"]

    def test_add_project_rejects_relative_path(self, tmp_path):
        """add_project rejects relative repo_path with ValueError."""
        from web.skills.code_agent import projects as proj_mod

        _patch_dirs(proj_mod, tmp_path)

        with pytest.raises(ValueError, match="absolute"):
            proj_mod.add_project("bad", "relative/path", source="local")

    def test_add_project_rejects_invalid_name(self, tmp_path):
        """add_project rejects names with path separators."""
        from web.skills.code_agent import projects as proj_mod

        _patch_dirs(proj_mod, tmp_path)

        with pytest.raises(ValueError):
            proj_mod.add_project("../../evil", "/tmp", source="local")

    def test_add_project_non_git_folder_raises_not_git_repo_error(self, tmp_path):
        """A plain (non-git) folder raises NotGitRepoError, not a generic ValueError,
        so callers (the route) can distinguish it and offer to fix it."""
        from web.skills.code_agent import projects as proj_mod

        _patch_dirs(proj_mod, tmp_path)

        plain_folder = tmp_path / "not-a-repo"
        plain_folder.mkdir()

        with pytest.raises(proj_mod.NotGitRepoError):
            proj_mod.add_project("not-a-repo", str(plain_folder), source="local")
        # Never partially registered — the project must not exist post-failure.
        assert not (proj_mod.PROJECTS_DIR / "not-a-repo").exists()

    def test_add_project_init_git_true_initializes_and_succeeds(self, tmp_path):
        """init_git=True runs `git init` in-place on a non-git folder and the
        add then succeeds, unblocking users who start from a plain folder."""
        from web.skills.code_agent import projects as proj_mod

        _patch_dirs(proj_mod, tmp_path)

        plain_folder = tmp_path / "fresh-project"
        plain_folder.mkdir()
        assert not (plain_folder / ".git").exists()

        proj_mod.add_project(
            "fresh-project", str(plain_folder), source="local", init_git=True
        )

        assert (plain_folder / ".git").exists()
        assert (proj_mod.PROJECTS_DIR / "fresh-project").exists()


class TestActiveProject:
    def test_get_active_project_returns_none_if_unset(self, tmp_path):
        """get_active_project returns None when config has no active_project."""
        from web.skills.code_agent import projects as proj_mod

        _patch_dirs(proj_mod, tmp_path)

        result = proj_mod.get_active_project()
        assert result is None

    def test_set_active_project_persists(self, tmp_path):
        """set_active_project → get_active_project returns same name."""
        from web.skills.code_agent import projects as proj_mod

        _patch_dirs(proj_mod, tmp_path)

        proj_mod.set_active_project("my-project")
        assert proj_mod.get_active_project() == "my-project"

    def test_list_projects_empty_on_fresh_install(self, tmp_path):
        """list_projects returns [] when no projects added."""
        from web.skills.code_agent import projects as proj_mod

        _patch_dirs(proj_mod, tmp_path)

        assert proj_mod.list_projects() == []

    def test_project_dir_path(self, tmp_path):
        """project_dir('foo') returns PROJECTS_DIR / 'foo'."""
        from web.skills.code_agent import projects as proj_mod

        _patch_dirs(proj_mod, tmp_path)

        result = proj_mod.project_dir("foo")
        assert result == proj_mod.PROJECTS_DIR / "foo"
