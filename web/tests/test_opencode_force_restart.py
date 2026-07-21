"""force_restart_instance + get_mcp_status — the user-triggered escape hatch
for "this session's config is stale" (e.g. an MCP config file was edited
after the server started, which OpenCode only reads at startup). Distinct
from ensure_instance()'s adopt-instead-of-kill: this ALWAYS kills and
respawns, regardless of whether the current process is healthy.
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from skills.opencode_agent import instance_manager as im


@pytest.fixture(autouse=True)
def _isolate_instances(monkeypatch):
    monkeypatch.setattr(im, "_instances", {})


class TestForceRestart:
    def test_kills_live_in_memory_instance_and_respawns(self, monkeypatch):
        live = im.OpencodeServerInstance(
            project_id="proj", repo_path="/repo", port=8100, pid=111,
            password="oldpass", status="running",
        )
        im._instances["proj"] = live
        terminated = []
        monkeypatch.setattr(im, "_terminate_instance", lambda inst: terminated.append(inst))
        fresh = im.OpencodeServerInstance(
            project_id="proj", repo_path="/repo", port=8101, pid=222,
            password="newpass", status="running",
        )
        monkeypatch.setattr(im, "_spawn_instance", lambda pid, repo: fresh)

        result = im.force_restart_instance("proj", "/repo")

        assert terminated == [live], "must kill the currently-tracked instance, even though it's healthy"
        assert result is fresh
        assert "proj" not in im._instances or im._instances.get("proj") is not live

    def test_no_in_memory_instance_but_persisted_one_is_killed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(im, "_INSTANCE_DIR", tmp_path)
        (tmp_path / "proj.json").write_text(json.dumps({
            "project_id": "proj", "repo_path": "/repo", "port": 8100,
            "pid": 333, "password": "savedpass", "status": "running",
        }), encoding="utf-8")
        terminated = []
        monkeypatch.setattr(im, "_terminate_instance", lambda inst: terminated.append(inst))
        fresh = object()
        monkeypatch.setattr(im, "_spawn_instance", lambda pid, repo: fresh)

        result = im.force_restart_instance("proj", "/repo")

        assert len(terminated) == 1
        assert terminated[0].pid == 333
        assert terminated[0].password == "savedpass"
        assert result is fresh

    def test_nothing_tracked_at_all_just_spawns(self, tmp_path, monkeypatch):
        monkeypatch.setattr(im, "_INSTANCE_DIR", tmp_path)  # empty
        terminated = []
        monkeypatch.setattr(im, "_terminate_instance", lambda inst: terminated.append(inst))
        fresh = object()
        monkeypatch.setattr(im, "_spawn_instance", lambda pid, repo: fresh)

        result = im.force_restart_instance("proj", "/repo")

        assert terminated == []
        assert result is fresh


class TestGetMcpStatus:
    def test_parses_successful_response(self, monkeypatch):
        import urllib.request

        class _FakeResp:
            status = 200
            def read(self): return json.dumps({"chrome-devtools": {"status": "connected"}}).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _FakeResp())
        result = im.get_mcp_status(8100, "pw")
        assert result == {"chrome-devtools": {"status": "connected"}}

    def test_returns_empty_dict_on_network_error(self, monkeypatch):
        import urllib.request

        def _raise(req, timeout=None):
            raise OSError("connection refused")

        monkeypatch.setattr(urllib.request, "urlopen", _raise)
        assert im.get_mcp_status(8100, "pw") == {}

    def test_returns_empty_dict_on_non_200(self, monkeypatch):
        import urllib.request
        import urllib.error

        def _raise(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 401, "unauthorized", None, None)

        monkeypatch.setattr(urllib.request, "urlopen", _raise)
        assert im.get_mcp_status(8100, "wrongpw") == {}
