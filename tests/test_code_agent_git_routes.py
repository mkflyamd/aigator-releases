"""Branch and worktree routes, and the worktree parameter on the read routes."""

import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import code_agent
from security import verify_csrf
from skills.code_agent import projects


def git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    home = tmp_path / ".gator"
    monkeypatch.setattr(projects, "GATOR_HOME", home)
    monkeypatch.setattr(projects, "PROJECTS_DIR", home / "projects")
    monkeypatch.setattr(projects, "CONFIG_FILE", home / "code_agent_projects.json")
    repo = tmp_path / "proj"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    (repo / "a.txt").write_text("one\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "first")
    projects._save_config(
        {"active_project": None, "projects": {"demo": {"repo_path": str(repo), "source": "local"}}}
    )
    app = FastAPI()
    app.include_router(code_agent.router, prefix="/api/code_agent")
    app.dependency_overrides[verify_csrf] = lambda: None
    c = TestClient(app)
    c.repo = repo
    return c


def post(c, path, **body):
    return c.post(f"/api/code_agent/git/{path}", json={"project_name": "demo", **body})


def test_branches_route_lists_branches_and_worktrees(client):
    git(client.repo, "branch", "feature")
    b = client.get("/api/code_agent/git/branches", params={"project_name": "demo"}).json()
    assert b["current"] == "main" and {x["name"] for x in b["local"]} == {"main", "feature"}
    w = client.get("/api/code_agent/git/worktrees", params={"project_name": "demo"}).json()
    assert [x["branch"] for x in w["worktrees"]] == ["main"]


def test_unknown_project_is_404(client):
    assert client.get("/api/code_agent/git/branches", params={"project_name": "nope"}).status_code == 404


def test_branch_create_checkout_and_delete_round_trip(client):
    assert post(client, "branch", name="feature").status_code == 200
    (client.repo / "b.txt").write_text("b\n")
    git(client.repo, "add", ".")
    git(client.repo, "commit", "-m", "work")
    assert post(client, "checkout", name="main").status_code == 200
    assert client.request(
        "DELETE", "/api/code_agent/git/branch", json={"project_name": "demo", "name": "feature"}
    ).status_code == 409  # unmerged work is never force-deleted
    git(client.repo, "branch", "done")
    assert client.request(
        "DELETE", "/api/code_agent/git/branch", json={"project_name": "demo", "name": "done"}
    ).status_code == 200


def test_checkout_dirty_tree_is_a_409_with_a_code_the_ui_can_confirm(client):
    git(client.repo, "branch", "feature")
    (client.repo / "a.txt").write_text("edit\n")
    r = post(client, "checkout", name="feature")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "dirty"
    assert post(client, "checkout", name="feature", confirm_dirty=True).status_code == 200


def test_bad_branch_name_is_a_400(client):
    assert post(client, "checkout", name="--force").status_code == 400


def test_worktree_add_then_remove(client):
    made = post(client, "worktree", branch="feature")
    assert made.status_code == 200
    path = made.json()["path"]
    assert Path(path).is_dir()
    gone = client.request(
        "DELETE", "/api/code_agent/git/worktree", json={"project_name": "demo", "path": path}
    )
    assert gone.status_code == 200 and not Path(path).exists()


def test_read_routes_follow_a_listed_worktree_only(client, tmp_path):
    path = post(client, "worktree", branch="feature").json()["path"]
    (Path(path) / "only_here.txt").write_text("x\n")
    status = client.get("/api/code_agent/git/status", params={"project_name": "demo", "worktree": path}).json()
    assert [u["file"] for u in status["untracked"]] == ["only_here.txt"]
    main = client.get("/api/code_agent/git/status", params={"project_name": "demo"}).json()
    assert main["untracked"] == []
    tree = client.get("/api/code_agent/files/tree", params={"project_name": "demo", "worktree": path}).json()
    assert "only_here.txt" in {e["name"] for e in tree["entries"]}
    outside = client.get(
        "/api/code_agent/git/status", params={"project_name": "demo", "worktree": str(tmp_path)}
    )
    assert outside.status_code == 400


def test_discard_runs_inside_the_chosen_worktree(client):
    path = post(client, "worktree", branch="feature").json()["path"]
    (Path(path) / "a.txt").write_text("changed in worktree\n")
    r = post(client, "discard", file="a.txt", worktree=path)
    assert r.status_code == 200
    assert (Path(path) / "a.txt").read_text() == "one\n"
