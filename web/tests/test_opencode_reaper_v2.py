"""OpenCode registry v2: intrinsic ownership (from --port) + authoritative
liveness (real server pid / port-probe, never the cmd.exe shim) + OWN-ONLY
reaping (never touches a peer instance's servers — the recurring cross-instance
kill danger is structurally impossible). Fixes the reload-orphan memory pile-up.
"""
import os
import sys
import json
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from skills.opencode_agent import instance_manager as im


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(im, "_instances", {})
    monkeypatch.setattr(im, "_own_port_cache", None)  # re-derive per test


def _write_rec(tmp_path, project_id, **fields):
    rec = {"project_id": project_id, "repo_path": "/r", "port": 8100, "pid": 1,
           "password": "pw", "status": "running", "last_activity": time.time(),
           "owner_port": 8000, "server_pid": 0}
    rec.update(fields)
    (tmp_path / f"{project_id}.json").write_text(json.dumps(rec), encoding="utf-8")
    return rec


# ── ownership ────────────────────────────────────────────────────────────────

def test_own_port_from_argv(monkeypatch):
    monkeypatch.setattr(im.sys, "argv", ["uvicorn", "web.app:app", "--port", "8002", "--reload"])
    monkeypatch.delenv("GATOR_INSTANCE_PORT", raising=False)
    assert im._own_port() == 8002


def test_own_port_from_argv_equals_form(monkeypatch):
    monkeypatch.setattr(im.sys, "argv", ["uvicorn", "--port=8100"])
    monkeypatch.delenv("GATOR_INSTANCE_PORT", raising=False)
    assert im._own_port() == 8100


def test_own_port_env_fallback(monkeypatch):
    monkeypatch.setattr(im.sys, "argv", ["python", "-c", "x"])   # no --port
    monkeypatch.setenv("GATOR_INSTANCE_PORT", "8002")
    assert im._own_port() == 8002


def test_own_port_default_8000(monkeypatch):
    monkeypatch.setattr(im.sys, "argv", ["python"])
    monkeypatch.delenv("GATOR_INSTANCE_PORT", raising=False)
    assert im._own_port() == 8000


# ── authoritative liveness ─────────────────────────────────────────────────────

def test_server_alive_via_port_200(monkeypatch):
    monkeypatch.setattr(im, "_port_config_status", lambda port, pw: 200)
    assert im._server_alive({"port": 8100, "password": "pw", "server_pid": 0}) is True


def test_server_alive_via_port_401_legacy_no_password(monkeypatch):
    # A 401 proves the HTTP server is UP — critical for legacy password-less records.
    monkeypatch.setattr(im, "_port_config_status", lambda port, pw: 401)
    assert im._server_alive({"port": 8100, "password": "", "server_pid": 0}) is True


def test_server_alive_false_when_connection_refused(monkeypatch):
    monkeypatch.setattr(im, "_port_config_status", lambda port, pw: 0)
    assert im._server_alive({"port": 8100, "password": "pw", "server_pid": 0}) is False


def test_server_ready_requires_200(monkeypatch):
    monkeypatch.setattr(im, "_port_config_status", lambda port, pw: 200)
    assert im._server_ready({"port": 8100, "password": "pw"}) is True
    monkeypatch.setattr(im, "_port_config_status", lambda port, pw: 401)
    assert im._server_ready({"port": 8100, "password": "pw"}) is False  # up but not usable
    assert im._server_ready({"port": 8100, "password": ""}) is False    # no creds


# ── reconcile (startup) ────────────────────────────────────────────────────────

def test_reconcile_removes_dead_records(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "_INSTANCE_DIR", tmp_path)
    monkeypatch.setattr(im, "_own_port", lambda: 8000)
    _write_rec(tmp_path, "dead", owner_port=8000)
    monkeypatch.setattr(im, "_server_alive", lambda rec: False)
    im.reconcile_own_records()
    assert not (tmp_path / "dead.json").exists()


def test_reconcile_leaves_alive_records(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "_INSTANCE_DIR", tmp_path)
    monkeypatch.setattr(im, "_own_port", lambda: 8000)
    _write_rec(tmp_path, "live", owner_port=8000)
    monkeypatch.setattr(im, "_server_alive", lambda rec: True)
    im.reconcile_own_records()
    assert (tmp_path / "live.json").exists()  # left for on-demand adoption


def test_reconcile_ignores_peer_records(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "_INSTANCE_DIR", tmp_path)
    monkeypatch.setattr(im, "_own_port", lambda: 8000)
    _write_rec(tmp_path, "peer", owner_port=8002)  # workbench's — not mine
    monkeypatch.setattr(im, "_server_alive", lambda rec: False)
    im.reconcile_own_records()
    assert (tmp_path / "peer.json").exists(), "must never touch a peer's record"


# ── reap_own_idle (own-only) ───────────────────────────────────────────────────

def _mock_reap(monkeypatch, alive=True, ready=True, terminated=None):
    monkeypatch.setattr(im, "_own_port", lambda: 8000)
    monkeypatch.setattr(im, "_server_alive", lambda rec: alive)
    monkeypatch.setattr(im, "_server_ready", lambda rec: ready)
    if terminated is not None:
        monkeypatch.setattr(im, "_terminate_record", lambda rec: terminated.append(rec.get("project_id")))


def test_reap_own_idle_ready_and_idle(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "_INSTANCE_DIR", tmp_path)
    term = []
    _mock_reap(monkeypatch, alive=True, ready=True, terminated=term)
    _write_rec(tmp_path, "idle", owner_port=8000, last_activity=time.time() - im.IDLE_TIMEOUT_SECONDS - 60)
    im.reap_own_idle()
    assert term == ["idle"]
    assert not (tmp_path / "idle.json").exists()


def test_reap_own_idle_leaves_active(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "_INSTANCE_DIR", tmp_path)
    term = []
    _mock_reap(monkeypatch, alive=True, ready=True, terminated=term)
    _write_rec(tmp_path, "active", owner_port=8000, last_activity=time.time())  # fresh
    im.reap_own_idle()
    assert term == []
    assert (tmp_path / "active.json").exists()


def test_reap_own_idle_reaps_stuck_starting(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "_INSTANCE_DIR", tmp_path)
    term = []
    _mock_reap(monkeypatch, alive=True, ready=False, terminated=term)  # alive but never ready
    _write_rec(tmp_path, "stuck", owner_port=8000, last_activity=time.time() - 200)
    im.reap_own_idle()
    assert term == ["stuck"]


def test_reap_own_idle_removes_dead(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "_INSTANCE_DIR", tmp_path)
    term = []
    _mock_reap(monkeypatch, alive=False, ready=False, terminated=term)
    _write_rec(tmp_path, "gone", owner_port=8000)
    im.reap_own_idle()
    assert not (tmp_path / "gone.json").exists()
    assert term == [], "dead server needs no terminate"


def test_reap_own_idle_never_touches_peer(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "_INSTANCE_DIR", tmp_path)
    term = []
    _mock_reap(monkeypatch, alive=True, ready=True, terminated=term)
    # peer-owned, idle — must be left ENTIRELY alone (the cross-instance-kill guard)
    _write_rec(tmp_path, "peer", owner_port=8002, last_activity=time.time() - im.IDLE_TIMEOUT_SECONDS - 60)
    im.reap_own_idle()
    assert term == []
    assert (tmp_path / "peer.json").exists()


def test_terminate_kills_real_server_pid_not_just_shim(monkeypatch):
    # The "restart didn't work" bug: _terminate_instance taskkill'd only the
    # cmd.exe shim pid, which is usually already dead while opencode.exe lives →
    # the real server survived. It must kill the REAL server_pid.
    monkeypatch.setattr(im.sys, "platform", "win32")
    monkeypatch.setattr(im.time, "sleep", lambda s: None)
    calls = []
    monkeypatch.setattr(im.subprocess, "run", lambda argv, **k: calls.append(argv))
    monkeypatch.setattr(im, "_pid_alive", lambda pid: pid == 4242)  # server alive, shim(1) dead
    inst = im.OpencodeServerInstance(project_id="p", repo_path="/r", port=8100, pid=1,
                                     password="pw", server_pid=4242)
    im._terminate_instance(inst)
    killed = [a[2] for a in calls if a and a[0] == "taskkill"]
    assert "4242" in killed, "must tree-kill the REAL opencode server pid"


def test_terminate_resolves_server_pid_from_port_when_unknown(monkeypatch):
    monkeypatch.setattr(im.sys, "platform", "win32")
    monkeypatch.setattr(im.time, "sleep", lambda s: None)
    monkeypatch.setattr(im, "_resolve_server_pid", lambda port: 5555)
    monkeypatch.setattr(im, "_pid_alive", lambda pid: pid == 5555)
    calls = []
    monkeypatch.setattr(im.subprocess, "run", lambda argv, **k: calls.append(argv))
    inst = im.OpencodeServerInstance(project_id="p", repo_path="/r", port=8100, pid=1,
                                     password="pw", server_pid=0)  # unknown → resolve from port
    im._terminate_instance(inst)
    killed = [a[2] for a in calls if a and a[0] == "taskkill"]
    assert "5555" in killed


def test_reap_own_idle_skips_when_spawn_lock_held(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "_INSTANCE_DIR", tmp_path)
    term = []
    _mock_reap(monkeypatch, alive=True, ready=True, terminated=term)
    _write_rec(tmp_path, "busy", owner_port=8000, last_activity=time.time() - im.IDLE_TIMEOUT_SECONDS - 60)
    # Hold the project's spawn lock → a spawn/adopt is "in progress" → reaper skips.
    lock = im._get_spawn_lock("busy")
    lock.acquire()
    try:
        im.reap_own_idle()
    finally:
        lock.release()
    assert term == [], "must not reap a project whose spawn lock is held"
    assert (tmp_path / "busy.json").exists()
