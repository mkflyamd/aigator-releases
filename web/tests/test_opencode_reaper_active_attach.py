"""Reaper must not kill a server that has a live terminal attached, and
ensure_instance must verify process identity (not just pid-alive).

Root cause of the recurring "Failed to send prompt / unable to connect": the
30-min idle reaper measured idleness from Gator round-trips, but prompts typed
in the terminal go straight to the server (bypassing Gator), so an actively-used
terminal looked idle and got reaped out from under the user. Fix: the reaper
consults a live-attach checker (real PTY liveness) and skips ready servers with
an open terminal; PID-reuse is guarded by an image check.
"""

import os
import sys
import json
import time
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from skills.opencode_agent import instance_manager as im


def _idle_record(tmp_path, project_id="proj", owner=9000):
    rec = {
        "project_id": project_id,
        "repo_path": "r",
        "port": 8101,
        "pid": 0,
        "server_pid": 0,
        "password": "pw",
        "status": "running",
        "owner_port": owner,
        "last_activity": time.time() - (im.IDLE_TIMEOUT_SECONDS + 300),
    }
    p = tmp_path / f"{project_id}.json"
    p.write_text(json.dumps(rec), encoding="utf-8")
    return p, rec


def _wire_reaper(monkeypatch, path, rec, alive=True, ready=True, own=9000):
    monkeypatch.setattr(im, "_own_port", lambda: own)
    monkeypatch.setattr(im, "_iter_records", lambda: iter([(path, dict(rec))]))
    monkeypatch.setattr(im, "_server_alive", lambda r: alive)
    monkeypatch.setattr(im, "_server_ready", lambda r: ready)
    killed = []
    monkeypatch.setattr(im, "_terminate_record", lambda r: killed.append(r))
    return killed


class TestReaperActiveAttach:
    def test_skips_ready_server_with_live_attach(self, monkeypatch, tmp_path):
        path, rec = _idle_record(tmp_path)
        killed = _wire_reaper(monkeypatch, path, rec)
        monkeypatch.setattr(im, "active_attach_checker", lambda pid: True)
        im.reap_own_idle()
        assert killed == [], (
            "a server with a live attached terminal must never be reaped"
        )
        assert path.exists(), "its record must survive"
        refreshed = json.loads(path.read_text())["last_activity"]
        assert refreshed > rec["last_activity"], (
            "last_activity must be refreshed on skip"
        )

    def test_reaps_idle_server_without_attach(self, monkeypatch, tmp_path):
        path, rec = _idle_record(tmp_path)
        killed = _wire_reaper(monkeypatch, path, rec)
        monkeypatch.setattr(im, "active_attach_checker", lambda pid: False)
        im.reap_own_idle()
        assert len(killed) == 1 and killed[0]["project_id"] == "proj", (
            "an idle server with no live terminal must still be reaped"
        )
        assert not path.exists(), "its record must be removed"

    def test_stuck_starting_server_reaped_even_with_attach(self, monkeypatch, tmp_path):
        # A never-ready (wedged boot) server must not be pinned open by an attach.
        path, rec = _idle_record(tmp_path)
        killed = _wire_reaper(monkeypatch, path, rec, ready=False)
        monkeypatch.setattr(im, "active_attach_checker", lambda pid: True)
        im.reap_own_idle()
        assert len(killed) == 1, (
            "a stuck-starting server is reaped regardless of attach claims"
        )


class TestHasActiveAttach:
    def test_none_hook_returns_false(self, monkeypatch):
        monkeypatch.setattr(im, "active_attach_checker", None)
        assert im._has_active_attach("x") is False

    def test_hook_result_passed_through(self, monkeypatch):
        monkeypatch.setattr(im, "active_attach_checker", lambda p: True)
        assert im._has_active_attach("x") is True
        monkeypatch.setattr(im, "active_attach_checker", lambda p: False)
        assert im._has_active_attach("x") is False

    def test_hook_exception_is_swallowed(self, monkeypatch):
        def boom(p):
            raise RuntimeError("checker blew up")

        monkeypatch.setattr(im, "active_attach_checker", boom)
        assert im._has_active_attach("x") is False, (
            "a broken checker must not wedge the reaper"
        )


class TestPidIsOpencode:
    def test_false_for_nonpositive(self):
        assert im._pid_is_opencode(0) is False
        assert im._pid_is_opencode(-1) is False

    def test_true_only_for_opencode_image(self, monkeypatch):
        class FakeProc:
            def __init__(self, pid):
                self.pid = pid

            def exe(self):
                return r"C:\somewhere\node\node_modules\opencode-ai\bin\opencode.exe"

        monkeypatch.setitem(
            sys.modules, "psutil", types.SimpleNamespace(Process=FakeProc)
        )
        assert im._pid_is_opencode(1234) is True

    def test_false_for_recycled_pid_other_image(self, monkeypatch):
        class FakeProc:
            def __init__(self, pid):
                self.pid = pid

            def exe(self):
                return r"C:\Windows\System32\notepad.exe"

        monkeypatch.setitem(
            sys.modules, "psutil", types.SimpleNamespace(Process=FakeProc)
        )
        assert im._pid_is_opencode(1234) is False


class TestProjectHasLiveAttach:
    def test_viewed_pty_protects_dead_pruned(self, monkeypatch):
        import routes.opencode_routes as r
        from routes import terminal

        r._attach_by_project.clear()
        r._attach_by_project["proj"] = {"live1", "dead1"}
        monkeypatch.setattr(terminal, "is_pty_alive", lambda s: s == "live1")
        monkeypatch.setattr(terminal, "is_pty_viewed", lambda s: s == "live1")
        assert r._project_has_live_attach("proj") is True
        assert r._attach_by_project["proj"] == {"live1"}, "dead pty must be pruned"

    def test_alive_but_not_viewed_does_not_protect_but_is_kept(self, monkeypatch):
        # THE LEAK FIX: a closed tab leaves the attach process alive but nothing
        # viewing it — that must NOT protect the server, yet the still-alive pty
        # stays registered so a reconnect can re-view it.
        import routes.opencode_routes as r
        from routes import terminal

        r._attach_by_project.clear()
        r._attach_by_project["proj"] = {"orphan"}
        monkeypatch.setattr(terminal, "is_pty_alive", lambda s: True)
        monkeypatch.setattr(terminal, "is_pty_viewed", lambda s: False)
        assert r._project_has_live_attach("proj") is False, (
            "an alive-but-unviewed (closed-tab) terminal must not pin the server open"
        )
        assert r._attach_by_project.get("proj") == {"orphan"}, (
            "a still-alive pty is kept so a reconnect can re-view it"
        )

    def test_all_dead_returns_false_and_drops_project(self, monkeypatch):
        import routes.opencode_routes as r
        from routes import terminal

        r._attach_by_project.clear()
        r._attach_by_project["proj2"] = {"deadA", "deadB"}
        monkeypatch.setattr(terminal, "is_pty_alive", lambda s: False)
        monkeypatch.setattr(terminal, "is_pty_viewed", lambda s: False)
        assert r._project_has_live_attach("proj2") is False
        assert "proj2" not in r._attach_by_project, (
            "an all-dead project must be dropped"
        )

    def test_unknown_project_false(self):
        import routes.opencode_routes as r

        r._attach_by_project.pop("nope", None)
        assert r._project_has_live_attach("nope") is False


class TestIsPtyViewed:
    def _mk(self, monkeypatch, alive=True, ws_clients=0, disconnected_ago=None):
        from routes import terminal
        import time as _t

        entry = {
            "done": False,
            "ws_clients": ws_clients,
            "ws_disconnected_at": (
                None if disconnected_ago is None else _t.time() - disconnected_ago
            ),
        }

        class _P:
            def isalive(self_inner):
                return alive

        entry["pty"] = _P()
        monkeypatch.setattr(terminal, "_pty_sessions", {"s": entry})
        return terminal

    def test_connected_is_viewed(self, monkeypatch):
        t = self._mk(monkeypatch, alive=True, ws_clients=1)
        assert t.is_pty_viewed("s") is True

    def test_recently_disconnected_within_grace_is_viewed(self, monkeypatch):
        t = self._mk(monkeypatch, alive=True, ws_clients=0, disconnected_ago=10)
        assert t.is_pty_viewed("s", grace_seconds=90) is True

    def test_disconnected_past_grace_not_viewed(self, monkeypatch):
        t = self._mk(monkeypatch, alive=True, ws_clients=0, disconnected_ago=600)
        assert t.is_pty_viewed("s", grace_seconds=90) is False

    def test_dead_process_never_viewed(self, monkeypatch):
        t = self._mk(monkeypatch, alive=False, ws_clients=5)
        assert t.is_pty_viewed("s") is False

    def test_unknown_session_not_viewed(self, monkeypatch):
        from routes import terminal

        monkeypatch.setattr(terminal, "_pty_sessions", {})
        assert terminal.is_pty_viewed("nope") is False
