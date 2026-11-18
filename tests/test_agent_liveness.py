import json
import os
import subprocess
import sys
from pathlib import Path

import psutil
import pytest

import agent_liveness as live


def filetime(epoch: float) -> str:
    return str(int((epoch + 11644473600) * 1e7))


def own_created() -> float:
    return psutil.Process(os.getpid()).create_time()


def write_entry(pid, session_id, name="work", **extra):
    root = Path.home() / ".claude" / "sessions"
    root.mkdir(parents=True, exist_ok=True)
    entry = {"pid": pid, "sessionId": session_id, "name": name, "startedAt": 1_700_000_000_000,
             "pidDomain": "win32:HOST", **extra}
    (root / f"{pid}.json").write_text(json.dumps(entry), encoding="utf-8")


@pytest.fixture(autouse=True)
def _clean_registry():
    root = Path.home() / ".claude" / "sessions"
    if root.exists():
        for f in root.glob("*.json"):
            f.unlink()
    yield


def test_claude_probe_reports_a_live_process_with_matching_start_time():
    write_entry(os.getpid(), "s-1", procStart=filetime(own_created()))
    [p] = live.live_processes("claude", "s-1")
    assert p["pid"] == os.getpid() and p["session_id"] == "s-1" and p["name"] == "work"
    assert p["started_at"] == 1_700_000_000 and p["source"] == "claude-registry"


def test_claude_probe_rejects_a_reused_pid():
    write_entry(os.getpid(), "s-1", procStart=filetime(own_created() - 3600))
    assert live.live_processes("claude", "s-1") == []


def test_claude_probe_rejects_a_dead_pid():
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    write_entry(dead.pid, "s-1", procStart=filetime(own_created()))
    assert live.live_processes("claude", "s-1") == []


def test_claude_probe_without_proc_start_falls_back_to_started_at():
    write_entry(os.getpid(), "s-1", startedAt=int((own_created() + 5) * 1000))
    assert len(live.live_processes("claude", "s-1")) == 1
    write_entry(os.getpid(), "s-1", startedAt=int((own_created() - 3600) * 1000))
    assert live.live_processes("claude", "s-1") == []


def test_claude_probe_filters_by_session_and_lists_all_without_one():
    write_entry(os.getpid(), "s-1", procStart=filetime(own_created()))
    assert live.live_processes("claude", "other") == []
    assert [p["session_id"] for p in live.live_processes("claude")] == ["s-1"]


def test_claude_probe_skips_wsl_entries_and_unreadable_files(monkeypatch):
    monkeypatch.setattr(live.sys, "platform", "win32")
    write_entry(os.getpid(), "s-1", procStart=filetime(own_created()), pidDomain="linux:Ubuntu")
    (Path.home() / ".claude" / "sessions" / "junk.json").write_text("{not json", encoding="utf-8")
    assert live.live_processes("claude") == []


def test_agents_without_a_registry_report_nothing_and_unknown_agents_are_ignored():
    assert live.live_processes("codex", "s-1") == []
    assert live.live_processes("crush", "s-1") == []
    assert live.live_processes("nope", "s-1") == []


def test_a_new_agent_only_needs_a_probe_registered(monkeypatch):
    proc = {"pid": 1, "session_id": "s-1", "name": None, "started_at": 0.0, "source": "x"}
    monkeypatch.setitem(live.PROBES, "newagent", lambda session_id=None: [proc])
    assert live.live_processes("newagent", "s-1") == [proc]


def test_a_failing_probe_is_treated_as_nothing_live(monkeypatch):
    def boom(session_id=None):
        raise RuntimeError("x")

    monkeypatch.setitem(live.PROBES, "claude", boom)
    assert live.live_processes("claude", "s-1") == []
