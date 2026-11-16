"""Project list ordering and removal for the Code project picker."""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import code_agent
from security import verify_csrf
from skills.code_agent import projects


@pytest.fixture
def store(tmp_path, monkeypatch):
    home = tmp_path / ".gator"
    monkeypatch.setattr(projects, "GATOR_HOME", home)
    monkeypatch.setattr(projects, "PROJECTS_DIR", home / "projects")
    monkeypatch.setattr(projects, "CONFIG_FILE", home / "code_agent_projects.json")
    return home


def _seed(names):
    cfg = {"active_project": None, "projects": {n: {"repo_path": f"/r/{n}", "source": "local"} for n in names}}
    projects._save_config(cfg)


def test_list_projects_puts_the_most_recently_opened_first(store):
    _seed(["a", "b", "c"])
    projects.set_active_project("b")
    time.sleep(0.01)
    projects.set_active_project("c")
    assert [p["name"] for p in projects.list_projects()] == ["c", "b", "a"]


def test_never_opened_projects_keep_their_saved_order_after_opened_ones(store):
    _seed(["a", "b", "c"])
    projects.set_active_project("c")
    assert [p["name"] for p in projects.list_projects()] == ["c", "a", "b"]


def test_set_active_project_records_last_opened(store):
    _seed(["a"])
    before = time.time()
    projects.set_active_project("a")
    assert projects.get_project("a")["last_opened"] >= before


def test_remove_project_drops_it_from_the_list_and_keeps_the_folder(store, tmp_path):
    repo = tmp_path / "work"
    repo.mkdir()
    (repo / "keep.txt").write_text("mine", encoding="utf-8")
    projects._save_config({"active_project": None, "projects": {"w": {"repo_path": str(repo), "source": "local"}}})
    (projects.PROJECTS_DIR / "w").mkdir(parents=True)
    projects.remove_project("w")
    assert projects.get_project("w") is None
    assert not (projects.PROJECTS_DIR / "w").exists()
    assert (repo / "keep.txt").read_text(encoding="utf-8") == "mine"


def test_remove_project_never_deletes_a_cloned_repo_with_content(store):
    clone = projects.PROJECTS_DIR / "g"
    clone.mkdir(parents=True)
    (clone / "unpushed.txt").write_text("work", encoding="utf-8")
    projects._save_config({"active_project": None, "projects": {"g": {"repo_path": str(clone), "source": "github"}}})
    projects.remove_project("g")
    assert projects.get_project("g") is None
    assert (clone / "unpushed.txt").exists()


def test_removing_the_active_project_activates_the_next_most_recent(store):
    _seed(["a", "b", "c"])
    projects.set_active_project("a")
    time.sleep(0.01)
    projects.set_active_project("b")
    time.sleep(0.01)
    projects.set_active_project("c")
    projects.remove_project("c")
    assert projects.get_active_project() == "b"
    projects.remove_project("b")
    projects.remove_project("a")
    assert projects.get_active_project() is None


def test_removing_an_inactive_project_keeps_the_active_one(store):
    _seed(["a", "b"])
    projects.set_active_project("a")
    projects.remove_project("b")
    assert projects.get_active_project() == "a"


def test_remove_project_rejects_unknown_and_unsafe_names(store):
    _seed(["a"])
    with pytest.raises(ValueError):
        projects.remove_project("missing")
    with pytest.raises(ValueError):
        projects.remove_project("../a")


def _client():
    app = FastAPI()
    app.include_router(code_agent.router, prefix="/api/code_agent")
    app.dependency_overrides[verify_csrf] = lambda: None
    return TestClient(app)


def test_delete_route_removes_the_project(store):
    _seed(["a", "b"])
    projects.set_active_project("a")
    r = _client().delete("/api/code_agent/projects/b")
    assert r.status_code == 200
    assert [p["name"] for p in _client().get("/api/code_agent/projects").json()["projects"]] == ["a"]


def test_delete_route_404s_for_an_unknown_project(store):
    _seed(["a"])
    assert _client().delete("/api/code_agent/projects/nope").status_code == 404


def test_delete_route_requires_csrf(store):
    _seed(["a"])
    app = FastAPI()
    app.include_router(code_agent.router, prefix="/api/code_agent")
    assert TestClient(app).delete("/api/code_agent/projects/a").status_code in (401, 403)
    assert projects.get_project("a") is not None
