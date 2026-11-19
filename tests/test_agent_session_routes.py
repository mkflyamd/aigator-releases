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
    monkeypatch.setattr(
        asr.code_projects, "get_project",
        lambda name: {"name": name, "repo_path": "C:\\work\\app"} if name == "demo" else None,
    )
    monkeypatch.setattr(generic_agent, "is_installed", lambda a: a in ("claude", "codex"))
    monkeypatch.setattr(generic_agent, "linked_session_id", lambda pty: "c1" if pty == "p1" else None)
    monkeypatch.setattr(ags, "wsl_sessions", lambda repo: ([], False))
    monkeypatch.setattr(ags, "cached_wsl_records", lambda repo: [])
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


def live_claude(monkeypatch, name):
    import agent_liveness

    proc = {"pid": 7, "session_id": "c1", "name": name, "started_at": 5.0, "source": "claude-registry"}
    monkeypatch.setattr(agent_liveness, "live_processes", lambda agent, sid=None: [proc] if agent == "claude" else [])


def test_list_marks_sessions_open_elsewhere_and_prefers_the_live_name(scanned, monkeypatch):
    live_claude(monkeypatch, f"Live {FAKE}")
    data = client().get("/api/agent-sessions", params={"project_name": "demo"}).json()
    sessions = {s["id"]: s for s in data["sessions"]}
    assert sessions["c1"]["live_elsewhere"] is True
    assert sessions["c1"]["title"].startswith("Live ") and FAKE not in sessions["c1"]["title"]
    assert "live_elsewhere" not in sessions["x1"] and sessions["x1"]["title"].startswith("Use key")


def test_list_does_not_flag_a_session_gator_owns_but_shows_its_live_name(scanned, monkeypatch):
    live_claude(monkeypatch, "Live name")
    data = client().get("/api/agent-sessions", params={"project_name": "demo", "pty": ["claude:p1"]}).json()
    c1 = next(s for s in data["sessions"] if s["id"] == "c1")
    assert c1["pty_session_id"] == "p1" and "live_elsewhere" not in c1 and c1["title"] == "Live name"


def test_list_links_a_live_process_to_the_gator_terminal_that_owns_it(scanned, monkeypatch):
    import agent_liveness
    from routes import terminal

    live_claude(monkeypatch, "Live name")
    monkeypatch.setattr(terminal, "pty_pid_map", lambda: {99: "p-owner"})
    monkeypatch.setattr(agent_liveness, "owning_pty", lambda pid, owners: owners.get(99) if pid == 7 else None)
    data = client().get("/api/agent-sessions", params={"project_name": "demo"}).json()
    c1 = next(s for s in data["sessions"] if s["id"] == "c1")
    assert c1["pty_session_id"] == "p-owner" and "live_elsewhere" not in c1 and c1["title"] == "Live name"


def test_list_still_flags_a_process_no_gator_terminal_owns(scanned, monkeypatch):
    import agent_liveness
    from routes import terminal

    live_claude(monkeypatch, "Live name")
    monkeypatch.setattr(terminal, "pty_pid_map", lambda: {99: "p-owner"})
    monkeypatch.setattr(agent_liveness, "owning_pty", lambda pid, owners: None)
    data = client().get("/api/agent-sessions", params={"project_name": "demo"}).json()
    c1 = next(s for s in data["sessions"] if s["id"] == "c1")
    assert c1["live_elsewhere"] is True and "pty_session_id" not in c1


def test_list_keeps_the_stored_title_when_nothing_is_live(scanned):
    data = client().get("/api/agent-sessions", params={"project_name": "demo"}).json()
    c1 = next(s for s in data["sessions"] if s["id"] == "c1")
    assert c1["title"] == "Older claude" and "live_elsewhere" not in c1


def write_transcript(path: Path):
    lines = [
        {"type": "user", "cwd": "C:\\work\\app", "message": {"role": "user", "content": "hello"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": f"key {FAKE}"}]}},
    ]
    path.write_text("\n".join(json.dumps(o) for o in lines) + "\n", encoding="utf-8")


def test_preview_returns_redacted_messages(tmp_path, monkeypatch):
    p = tmp_path / "c1.jsonl"
    write_transcript(p)
    monkeypatch.setattr(ags, "find_session", lambda repo, agent, sid, **kw: {"agent": "claude", "path": str(p)})
    r = client().get("/api/agent-sessions/claude/c1/preview", params={"project_name": "demo"})
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert FAKE not in json.dumps(msgs) and "[REDACTED]" in msgs[1]["text"]


def test_preview_rejects_bad_agent_and_id():
    assert client().get("/api/agent-sessions/pi/c1/preview", params={"project_name": "demo"}).status_code == 400
    assert client().get("/api/agent-sessions/claude/bad%20id/preview", params={"project_name": "demo"}).status_code == 400


def test_preview_unknown_project_session_or_deleted_file_is_404(tmp_path, monkeypatch):
    assert client().get("/api/agent-sessions/claude/c1/preview", params={"project_name": "nope"}).status_code == 404
    monkeypatch.setattr(ags, "find_session", lambda repo, agent, sid, **kw: None)
    assert client().get("/api/agent-sessions/claude/c1/preview", params={"project_name": "demo"}).status_code == 404
    gone = {"agent": "claude", "path": str(tmp_path / "gone.jsonl")}
    monkeypatch.setattr(ags, "find_session", lambda repo, agent, sid, **kw: gone)
    assert client().get("/api/agent-sessions/claude/c1/preview", params={"project_name": "demo"}).status_code == 404


def test_app_includes_the_router():
    src = (Path(__file__).parent.parent / "web" / "app.py").read_text(encoding="utf-8")
    assert "from routes.agent_session_routes import router as agent_session_router" in src
    assert "app.include_router(agent_session_router)" in src
