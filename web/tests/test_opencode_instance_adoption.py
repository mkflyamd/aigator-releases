"""OpenCode instance adoption — fixes a real bug where Gator's own bookkeeping
being reset (dev hot-reload, or Gator restarting) while the real `opencode
serve` process stayed alive caused an unnecessary kill+respawn: a new random
password was issued, the freed port could be reused by a DIFFERENT project's
next spawn, and any already-attached client kept talking to its old
(now-wrong) port/password, surfacing as a raw 401 Unauthorized with no
recovery. Fix: persist the password and adopt a still-live, still-responsive
process instead of always assuming it's an orphan.
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from skills.opencode_agent import instance_manager as im


@pytest.fixture(autouse=True)
def _isolate_instances(monkeypatch):
    # _instances is module-level state - isolate each test from it.
    monkeypatch.setattr(im, "_instances", {})


def _make_persisted(tmp_path, monkeypatch, **overrides):
    monkeypatch.setattr(im, "_INSTANCE_DIR", tmp_path)
    data = {
        "project_id": "proj", "repo_path": "/repo", "port": 8123,
        "pid": 999, "password": "realpass", "status": "running",
        "last_activity": 0.0,
    }
    data.update(overrides)
    (tmp_path / "proj.json").write_text(json.dumps(data), encoding="utf-8")
    return data


class TestPersistIncludesPassword:
    def test_password_is_written(self, tmp_path, monkeypatch):
        monkeypatch.setattr(im, "_INSTANCE_DIR", tmp_path)
        inst = im.OpencodeServerInstance(
            project_id="p", repo_path="/r", port=1, pid=2, password="secret", status="running",
        )
        im._persist_instance(inst)
        data = json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))
        assert data.get("password") == "secret"


class TestAdoptInsteadOfKill:
    # v2: adoption is judged by REAL-SERVER READINESS (_server_ready — answers
    # /config with the saved password), never the cmd.exe shim pid.
    def test_adopts_live_responsive_process(self, tmp_path, monkeypatch):
        _make_persisted(tmp_path, monkeypatch)
        monkeypatch.setattr(im, "_server_ready", lambda rec: rec.get("password") == "realpass")
        monkeypatch.setattr(im, "_resolve_server_pid", lambda port: 4242)
        terminate_calls = []
        monkeypatch.setattr(im, "_terminate_instance", lambda inst: terminate_calls.append(inst))
        spawn_calls = []
        monkeypatch.setattr(im, "_spawn_instance", lambda pid, repo: spawn_calls.append((pid, repo)) or None)

        result = im._ensure_instance_locked("proj", "/repo")

        assert result.status == "running"
        assert result.password == "realpass"
        assert result.server_pid == 4242, "adopt resolves the REAL opencode pid"
        assert terminate_calls == [], "a ready server must NOT be terminated"
        assert spawn_calls == [], "a ready server must NOT trigger a fresh spawn"
        assert im._instances["proj"] is result

    def test_falls_back_to_respawn_when_password_missing(self, tmp_path, monkeypatch):
        # Pre-fix persisted record (no password) — not adoptable; remnant killed.
        _make_persisted(tmp_path, monkeypatch, password="")
        monkeypatch.setattr(im, "_server_ready", lambda rec: False)
        monkeypatch.setattr(im, "_server_alive", lambda rec: True)  # process up but bad creds
        terminate_calls = []
        monkeypatch.setattr(im, "_terminate_instance", lambda inst: terminate_calls.append(inst))
        spawned = object()
        monkeypatch.setattr(im, "_spawn_instance", lambda pid, repo: spawned)

        result = im._ensure_instance_locked("proj", "/repo")

        assert len(terminate_calls) == 1, "must terminate the unrecoverable remnant"
        assert result is spawned, "must fall back to a fresh spawn"

    def test_falls_back_when_saved_password_no_longer_works(self, tmp_path, monkeypatch):
        _make_persisted(tmp_path, monkeypatch, password="stale-password")
        monkeypatch.setattr(im, "_server_ready", lambda rec: False)  # responds but rejects creds
        monkeypatch.setattr(im, "_server_alive", lambda rec: True)
        terminate_calls = []
        monkeypatch.setattr(im, "_terminate_instance", lambda inst: terminate_calls.append(inst))
        spawned = object()
        monkeypatch.setattr(im, "_spawn_instance", lambda pid, repo: spawned)

        result = im._ensure_instance_locked("proj", "/repo")

        assert len(terminate_calls) == 1
        assert result is spawned

    def test_no_persisted_record_spawns_fresh(self, tmp_path, monkeypatch):
        monkeypatch.setattr(im, "_INSTANCE_DIR", tmp_path)  # empty dir, no proj.json
        spawned = object()
        monkeypatch.setattr(im, "_spawn_instance", lambda pid, repo: spawned)
        result = im._ensure_instance_locked("proj", "/repo")
        assert result is spawned

    def test_persisted_but_dead_server_spawns_fresh_without_terminate(self, tmp_path, monkeypatch):
        _make_persisted(tmp_path, monkeypatch)
        monkeypatch.setattr(im, "_server_ready", lambda rec: False)
        monkeypatch.setattr(im, "_server_alive", lambda rec: False)   # genuinely dead
        monkeypatch.setattr(im, "_pid_alive", lambda pid: False)
        terminate_calls = []
        monkeypatch.setattr(im, "_terminate_instance", lambda inst: terminate_calls.append(inst))
        spawned = object()
        monkeypatch.setattr(im, "_spawn_instance", lambda pid, repo: spawned)
        result = im._ensure_instance_locked("proj", "/repo")
        assert result is spawned
        assert terminate_calls == [], "nothing alive → nothing to terminate"
