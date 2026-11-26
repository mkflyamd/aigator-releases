import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_handoff as ah
import agent_sessions as ags
import generic_agent
from routes import agent_session_routes as asr

FAKE = "aigator-fake-api-key"


def client():
    app = FastAPI()
    app.include_router(asr.router)
    return TestClient(app)


def rec(agent, sid, title, last, source="windows"):
    return {"id": sid, "agent": agent, "title": title, "branch": "main", "started_at": last - 60,
            "last_active_at": last, "state": "done", "source": source,
            "path": f"C:\\secret\\{sid}.jsonl", "cwd": "C:\\work\\app"}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setattr(ags, "ensure_fresh", lambda repo: None)
    monkeypatch.setattr(
        asr.code_projects, "get_project",
        lambda name: {"name": name, "repo_path": "C:\\work\\app"} if name == "demo" else None,
    )
    monkeypatch.setattr(generic_agent, "is_installed", lambda a: a in ("claude", "codex"))
    monkeypatch.setattr(generic_agent, "linked_session_id", lambda pty: "c1" if pty == "p1" else None)
    monkeypatch.setattr(ags, "wsl_sessions", lambda repo: ([], False))
    monkeypatch.setattr(ah, "_configured_api_keys", lambda: [FAKE])
    monkeypatch.setattr(ah, "_session_started_at", lambda sid: None)


@pytest.fixture
def scanned(monkeypatch):
    seen = {}
    records = [
        rec("claude", "c1", "Older claude", 100),
        rec("codex", "x1", f"Use key {FAKE} here", 300),
    ]

    def fake(repo, *, homes=None, agents=ags.AGENTS):
        seen["repo"], seen["agents"] = repo, agents
        return [r for r in records if r["agent"] in agents]

    monkeypatch.setattr(ags, "scan_project", fake)
    return seen


def test_list_returns_public_records_newest_first_and_redacts_titles(scanned):
    r = client().get("/api/agent-sessions", params={"project_name": "demo"})
    assert r.status_code == 200
    data = r.json()
    assert [s["id"] for s in data["sessions"]] == ["x1", "c1"]
    assert data["wsl_pending"] is False
    assert all("path" not in s and "cwd" not in s for s in data["sessions"])
    assert FAKE not in data["sessions"][0]["title"] and "[REDACTED]" in data["sessions"][0]["title"]
    assert scanned["repo"] == "C:\\work\\app"


def test_list_unknown_project_is_404(scanned):
    assert client().get("/api/agent-sessions", params={"project_name": "nope"}).status_code == 404


def test_list_scans_only_installed_agents(scanned, monkeypatch):
    monkeypatch.setattr(generic_agent, "is_installed", lambda a: a == "claude")
    data = client().get("/api/agent-sessions", params={"project_name": "demo"}).json()
    assert scanned["agents"] == ("claude",)
    assert [s["id"] for s in data["sessions"]] == ["c1"]


def test_list_merges_wsl_records_and_reports_pending(scanned, monkeypatch):
    wsl = rec("claude", "w1", "From WSL", 200, source="wsl:Ubuntu")
    monkeypatch.setattr(ags, "wsl_sessions", lambda repo: ([wsl], True))
    data = client().get("/api/agent-sessions", params={"project_name": "demo"}).json()
    assert [s["id"] for s in data["sessions"]] == ["x1", "w1", "c1"]
    assert data["wsl_pending"] is True


def test_list_joins_live_terminals_by_pinned_id(scanned):
    r = client().get("/api/agent-sessions", params={"project_name": "demo", "pty": ["claude:p1", "junk", "claude:"]})
    assert r.status_code == 200
    joined = {s["id"]: s.get("pty_session_id") for s in r.json()["sessions"]}
    assert joined == {"x1": None, "c1": "p1"}


def test_list_joins_codex_by_start_time(scanned, monkeypatch):
    monkeypatch.setattr(ah, "_session_started_at", lambda sid: 200.0 if sid == "p9" else None)
    r = client().get("/api/agent-sessions", params={"project_name": "demo", "pty": "codex:p9"})
    assert {s["id"]: s.get("pty_session_id") for s in r.json()["sessions"]}["x1"] == "p9"


def test_list_refreshes_the_index_before_reading_it(scanned, monkeypatch):
    order = []
    monkeypatch.setattr(ags, "ensure_fresh", lambda repo: order.append(("fresh", repo)))
    real = ags.scan_project
    monkeypatch.setattr(ags, "scan_project", lambda *a, **kw: order.append("scan") or real(*a, **kw))
    client().get("/api/agent-sessions", params={"project_name": "demo"})
    assert order == [("fresh", "C:\\work\\app"), "scan"]


def test_preview_returns_redacted_messages(monkeypatch):
    stored = [{"role": "user", "text": "hello"}, {"role": "assistant", "text": f"key {FAKE}"}]
    monkeypatch.setattr(ags, "find_session", lambda repo, agent, sid, **kw: {"agent": "claude", "preview": stored})
    r = client().get("/api/agent-sessions/claude/c1/preview", params={"project_name": "demo"})
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert FAKE not in json.dumps(msgs) and "[REDACTED]" in msgs[1]["text"]


def test_preview_rejects_bad_agent_and_id():
    assert client().get("/api/agent-sessions/pi/c1/preview", params={"project_name": "demo"}).status_code == 400
    assert client().get("/api/agent-sessions/claude/bad%20id/preview", params={"project_name": "demo"}).status_code == 400


def test_preview_unknown_project_session_or_unreadable_store_is_404(monkeypatch):
    assert client().get("/api/agent-sessions/claude/c1/preview", params={"project_name": "nope"}).status_code == 404
    monkeypatch.setattr(ags, "find_session", lambda repo, agent, sid, **kw: None)
    assert client().get("/api/agent-sessions/claude/c1/preview", params={"project_name": "demo"}).status_code == 404
    monkeypatch.setattr(ags, "find_session", lambda repo, agent, sid, **kw: {"agent": "crush"})

    def unreadable(rec):
        raise OSError("database is gone")

    monkeypatch.setattr(ags, "preview", unreadable)
    assert client().get("/api/agent-sessions/claude/c1/preview", params={"project_name": "demo"}).status_code == 404


def test_app_includes_the_router():
    src = (Path(__file__).parent.parent / "web" / "app.py").read_text(encoding="utf-8")
    assert "from routes.agent_session_routes import router as agent_session_router" in src
    assert "app.include_router(agent_session_router)" in src
