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


def test_owning_pty_matches_a_process_to_the_pty_whose_process_is_its_ancestor():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert live.owning_pty(child.pid, {os.getpid(): "p1"}) == "p1"
        assert live.owning_pty(os.getpid(), {os.getpid(): "p1"}) == "p1"
        assert live.owning_pty(child.pid, {os.getpid() + 100000: "p2"}) is None
        assert live.owning_pty(child.pid, {}) is None
    finally:
        child.kill()
        child.wait()


def test_owning_pty_ignores_a_process_that_is_gone():
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    assert live.owning_pty(gone.pid, {os.getpid(): "p1"}) is None


class _Named:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class _Chain:
    def __init__(self, parents):
        self._parents = [_Named(n) for n in parents]

    def parents(self):
        return self._parents


def fake_chain(monkeypatch, parents):
    monkeypatch.setattr(live.psutil, "Process", lambda pid: _Chain(parents))


@pytest.mark.parametrize(
    "parents, label",
    [
        (["pwsh.exe", "Orca.exe", "explorer.exe"], "Orca"),
        (["Claude.exe", "explorer.exe"], "Claude desktop"),
        (["pwsh.exe", "WindowsTerminal.exe", "explorer.exe"], "Windows Terminal"),
        (["Code.exe"], "VS Code"),
        (["bash", "gnome-terminal-server", "systemd"], "Terminal"),
        (["pwsh.exe", "explorer.exe"], "PowerShell"),
        (["explorer.exe"], None),
        ([], None),
    ],
)
def test_location_label_names_the_app_a_process_runs_under(monkeypatch, parents, label):
    fake_chain(monkeypatch, parents)
    assert live.location_label(123) == label


def test_location_label_is_none_for_a_process_that_is_gone():
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    assert live.location_label(gone.pid) is None


def spawn_tree():
    """A python process that has one python grandchild; returns (child, grandchild_pid)."""
    code = (
        "import subprocess, sys, time;"
        "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
        "print(g.pid, flush=True); time.sleep(60)"
    )
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    return child, int(child.stdout.readline())


def register(child, session_id="s-1", **extra):
    write_entry(child.pid, session_id, procStart=filetime(psutil.Process(child.pid).create_time()), **extra)


def reap(child):
    child.kill()
    child.wait()
    child.stdout.close()


def created_of(child):
    return psutil.Process(child.pid).create_time()


def end(child, owners=None, *, created=None, session_id="s-1"):
    return live.takeover(
        "claude", session_id, owners or {}, child.pid, created if created is not None else created_of(child)
    )


@pytest.fixture
def closable(monkeypatch):
    """The test processes are plain python, which the allowlist rightly refuses."""
    monkeypatch.setattr(live, "closable", lambda agent, pid: (True, None))


def test_takeover_ends_the_registered_process_and_its_children_only(closable):
    child, grandchild = spawn_tree()
    try:
        register(child)
        assert end(child) == [child.pid]
        assert child.poll() is not None
        assert not psutil.pid_exists(grandchild)
        assert psutil.pid_exists(os.getpid())
    finally:
        reap(child)


def test_takeover_never_ends_a_process_a_gator_terminal_owns(closable):
    child, _ = spawn_tree()
    try:
        register(child)
        with pytest.raises(live.TakeoverError, match="Gator terminal"):
            end(child, {child.pid: "p1"})
        assert child.poll() is None
    finally:
        reap(child)


def test_takeover_never_ends_a_process_whose_pid_was_reused(closable):
    child, _ = spawn_tree()
    try:
        write_entry(child.pid, "s-1", procStart=filetime(created_of(child) - 3600))
        with pytest.raises(live.TakeoverError) as exc:
            end(child)
        assert exc.value.code == "process_changed"
        assert child.poll() is None
    finally:
        reap(child)


def test_takeover_never_ends_a_process_registered_for_another_session(closable):
    child, _ = spawn_tree()
    try:
        register(child, session_id="other")
        with pytest.raises(live.TakeoverError) as exc:
            end(child)
        assert exc.value.code == "process_changed"
        assert child.poll() is None
    finally:
        reap(child)


def test_takeover_is_bound_to_the_creation_time_the_user_confirmed(closable):
    child, _ = spawn_tree()
    try:
        register(child)
        with pytest.raises(live.TakeoverError) as exc:
            end(child, created=created_of(child) - 5)
        assert exc.value.code == "process_changed"
        assert child.poll() is None
    finally:
        reap(child)


def test_takeover_ends_nothing_when_a_new_process_took_over_the_session_after_the_dialog(closable):
    shown, _ = spawn_tree()
    replacement, _ = spawn_tree()
    try:
        shown_created = created_of(shown)
        shown.kill()
        shown.wait()
        register(replacement)
        with pytest.raises(live.TakeoverError) as exc:
            live.takeover("claude", "s-1", {}, shown.pid, shown_created)
        assert exc.value.code == "process_changed"
        assert replacement.poll() is None
    finally:
        reap(shown)
        reap(replacement)


def test_takeover_rechecks_pid_and_creation_time_before_signalling(closable, monkeypatch):
    child, grandchild = spawn_tree()
    try:
        register(child)
        real = live._confirmed_process
        calls = []

        def swapped_after_enumeration(pid, created):
            calls.append(pid)
            if len(calls) == 2:
                raise live.TakeoverError("changed", code="process_changed")
            return real(pid, created)

        monkeypatch.setattr(live, "_confirmed_process", swapped_after_enumeration)
        with pytest.raises(live.TakeoverError):
            end(child)
        assert len(calls) == 2
        assert child.poll() is None and psutil.pid_exists(grandchild)
    finally:
        reap(child)


def test_takeover_refuses_an_unknown_application():
    child, _ = spawn_tree()
    try:
        register(child)
        with pytest.raises(live.TakeoverError) as exc:
            end(child)
        assert exc.value.code == "not_closable"
        assert "yourself" in str(exc.value)
        assert child.poll() is None
    finally:
        reap(child)


def fake_proc(monkeypatch, name, cmdline=(), parents=("explorer",)):
    class Named:
        def __init__(self, n):
            self.n = n

        def name(self):
            return self.n

    class P:
        def __init__(self, pid):
            self.pid = pid

        def name(self):
            return name

        def cmdline(self):
            return list(cmdline)

        def parents(self):
            return [Named(n) for n in parents]

    monkeypatch.setattr(live.psutil, "Process", P)


@pytest.mark.parametrize(
    "name, cmdline, parents, ok",
    [
        ("claude.exe", [], ["WindowsTerminal.exe"], True),
        ("node.exe", ["node", "C:/x/claude-code/cli.js"], ["pwsh.exe"], True),
        ("node.exe", ["node", "server.js"], ["pwsh.exe"], False),
        ("python.exe", ["python", "claude.py"], ["pwsh.exe"], False),
        ("claude.exe", [], ["explorer.exe"], False),
    ],
)
def test_closable_allows_only_known_agent_processes_under_a_known_app(monkeypatch, name, cmdline, parents, ok):
    fake_proc(monkeypatch, name, cmdline, parents)
    allowed, reason = live.closable("claude", 123)
    assert allowed is ok
    assert (reason is None) is ok


def test_closable_refuses_agents_without_a_registry(monkeypatch):
    fake_proc(monkeypatch, "codex.exe", parents=["pwsh.exe"])
    assert live.closable("codex", 123)[0] is False


def test_describe_reports_what_the_user_confirms(monkeypatch):
    monkeypatch.setattr(live, "closable", lambda agent, pid: (True, None))
    monkeypatch.setattr(live, "location_label", lambda pid: "Orca")
    proc = {"pid": 7, "session_id": "s-1", "created": 1234.5}
    assert live.describe("claude", proc) == {
        "app": "Orca", "pid": 7, "created": 1234.5, "session_id": "s-1", "can_close": True, "reason": None,
    }


def test_describe_blocks_closing_when_gator_terminals_could_not_be_checked(monkeypatch):
    monkeypatch.setattr(live, "closable", lambda agent, pid: (True, None))
    monkeypatch.setattr(live, "location_label", lambda pid: "Orca")
    d = live.describe("claude", {"pid": 7, "session_id": "s-1", "created": 1.0}, owners_known=False)
    assert d["can_close"] is False and d["reason"]


def test_takeover_refuses_to_end_a_tree_that_contains_this_server(closable, monkeypatch):
    child, grandchild = spawn_tree()
    try:
        register(child)
        monkeypatch.setattr(live.os, "getpid", lambda: grandchild)
        with pytest.raises(live.TakeoverError):
            end(child)
        assert child.poll() is None and psutil.pid_exists(grandchild)
    finally:
        reap(child)


def test_takeover_reports_a_process_that_cannot_be_ended(closable, monkeypatch):
    child, _ = spawn_tree()
    try:
        register(child)

        def denied(self):
            raise psutil.AccessDenied(self.pid)

        monkeypatch.setattr(psutil.Process, "terminate", denied)
        monkeypatch.setattr(psutil.Process, "kill", denied)
        with pytest.raises(live.TakeoverError, match="could not"):
            end(child)
        assert child.poll() is None
    finally:
        monkeypatch.undo()
        reap(child)


def test_takeover_counts_an_exited_process_awaiting_its_parent_as_ended(closable, monkeypatch):
    class Zombie:
        def __init__(self, proc):
            self.pid = proc.pid

        def status(self):
            return psutil.STATUS_ZOMBIE

    real_wait = psutil.wait_procs

    def wait_leaving_zombies(procs, timeout=None):
        real_wait(procs, timeout=timeout)
        return [], [Zombie(p) for p in procs]

    child, _ = spawn_tree()
    try:
        register(child)
        monkeypatch.setattr(live.psutil, "wait_procs", wait_leaving_zombies)
        assert end(child) == [child.pid]
    finally:
        reap(child)


def test_takeover_logs_what_it_ends(closable, caplog):
    child, _ = spawn_tree()
    try:
        register(child)
        with caplog.at_level("WARNING"):
            end(child)
        assert str(child.pid) in caplog.text and "s-1" in caplog.text
    finally:
        reap(child)
