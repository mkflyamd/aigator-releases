"""Agents installed inside WSL are detected and launched through wsl.exe."""

import json
import time

import pytest

import generic_agent


@pytest.fixture(autouse=True)
def _wsl_state_in_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(generic_agent, "_WSL_STATE", tmp_path / "wsl-agents.json")


def _probe_env(monkeypatch, running, run_result="codex=/home/u/.local/bin/codex\n"):
    monkeypatch.setattr(generic_agent.sys, "platform", "win32")
    monkeypatch.setattr(generic_agent.shutil, "which", lambda n: "wsl.exe")
    monkeypatch.setattr(generic_agent, "_wsl_default_distro", lambda: "Ubuntu")
    monkeypatch.setattr(generic_agent, "wsl_distro_running", lambda d: running)
    calls = []

    def run(args, script=None):
        calls.append(args)
        return run_result

    monkeypatch.setattr(generic_agent, "_wsl_run", run)
    return calls


def _with_wsl(monkeypatch, found, windows=None):
    monkeypatch.setattr(generic_agent, "wsl_agents", lambda: ("Ubuntu", found))
    monkeypatch.setattr(generic_agent, "find_agent_binary", lambda a: (windows or {}).get(a))


def test_wsl_only_agent_counts_as_installed(monkeypatch):
    _with_wsl(monkeypatch, {"codex": "codex"})
    assert generic_agent.is_installed("codex") is True
    assert generic_agent.is_installed("claude") is False


def test_wsl_agent_launches_through_wsl_in_the_project_directory(monkeypatch):
    _with_wsl(monkeypatch, {"codex": "codex"})
    assert generic_agent.build_command("codex", "C:/proj dir") == [
        "wsl.exe", "-d", "Ubuntu", "--cd", "C:/proj dir", "--", "bash", "-lc", "exec codex",
    ]


def test_windows_install_wins_over_wsl(monkeypatch):
    _with_wsl(monkeypatch, {"codex": "codex"}, {"codex": "C:/bin/codex.exe"})
    assert generic_agent.build_command("codex", "C:/p") == ["C:/bin/codex.exe"]


def test_alias_and_extra_args_are_kept_for_wsl_agents(monkeypatch):
    _with_wsl(monkeypatch, {"kiro": "kiro-cli"})
    assert generic_agent.build_command("kiro", "C:/p")[-1] == "exec kiro-cli chat --tui"


def test_crush_is_never_launched_through_wsl(monkeypatch):
    _with_wsl(monkeypatch, {"crush": "crush"})
    assert generic_agent.is_installed("crush") is False
    assert generic_agent.build_command("crush", "C:/p") is None


def test_probe_output_keeps_only_native_linux_hits(monkeypatch):
    _probe_env(monkeypatch, True, "codex=/home/u/.local/bin/codex\npi=/mnt/c/npm/pi\n")
    assert generic_agent._wsl_probe() == ("Ubuntu", {"codex": "codex"})


def _save_state(**distros):
    generic_agent._WSL_STATE.write_text(json.dumps(distros), "utf-8")


def _saved(distro="Ubuntu"):
    return json.loads(generic_agent._WSL_STATE.read_text("utf-8"))[distro]


def test_first_probe_boots_the_distro_once_and_remembers_the_result(monkeypatch):
    calls = _probe_env(monkeypatch, False)
    assert generic_agent._wsl_probe() == ("Ubuntu", {"codex": "codex"})
    assert len(calls) == 1
    assert _saved()["found"] == {"codex": "codex"}


def test_a_stopped_distro_is_never_probed_again(monkeypatch):
    calls = _probe_env(monkeypatch, False)
    _save_state(Ubuntu={"found": {"claude": "claude"}, "found_at": 1})
    assert generic_agent._wsl_probe() == ("Ubuntu", {"claude": "claude"})
    assert calls == []


def test_a_running_distro_is_not_asked_again_while_the_saved_result_is_recent(monkeypatch):
    calls = _probe_env(monkeypatch, True)
    _save_state(Ubuntu={"found": {"claude": "claude"}, "found_at": time.time() - 60})
    assert generic_agent._wsl_probe() == ("Ubuntu", {"claude": "claude"})
    assert calls == []


def test_a_running_distro_is_reprobed_once_the_saved_result_is_old(monkeypatch):
    calls = _probe_env(monkeypatch, True)
    _save_state(Ubuntu={"found": {}, "found_at": time.time() - generic_agent._WSL_REPROBE_SECONDS - 1})
    assert generic_agent._wsl_probe() == ("Ubuntu", {"codex": "codex"})
    assert len(calls) == 1


def test_each_distro_keeps_its_own_saved_result(monkeypatch):
    calls = _probe_env(monkeypatch, False)
    _save_state(Debian={"found": {"claude": "claude"}, "found_at": 1})
    assert generic_agent._wsl_probe() == ("Ubuntu", {"codex": "codex"})
    assert len(calls) == 1
    assert _saved("Debian")["found"] == {"claude": "claude"}


def test_a_failed_probe_is_not_remembered(monkeypatch):
    _probe_env(monkeypatch, False, None)
    assert generic_agent._wsl_probe() == ("Ubuntu", {})
    assert not generic_agent._WSL_STATE.exists()


def test_a_damaged_state_file_does_not_start_a_stopped_distro_that_was_never_probed(monkeypatch):
    calls = _probe_env(monkeypatch, False)
    generic_agent._WSL_STATE.write_text("", "utf-8")
    assert generic_agent._wsl_probe() == ("Ubuntu", {"codex": "codex"})
    assert len(calls) == 1
    assert _saved()["found"] == {"codex": "codex"}


def test_concurrent_saves_keep_both_fields(monkeypatch):
    import threading

    def save(**fields):
        for _ in range(40):
            generic_agent._wsl_state_save("Ubuntu", **fields)

    threads = [
        threading.Thread(target=save, kwargs={"found": {"codex": "codex"}}),
        threading.Thread(target=save, kwargs={"codex_config": "x"}),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert _saved() == {"found": {"codex": "codex"}, "codex_config": "x"}


def test_redetect_asks_a_running_distro_but_never_starts_a_stopped_one(monkeypatch):
    calls = _probe_env(monkeypatch, True)
    monkeypatch.setattr(generic_agent, "wsl_agents", lambda: ("Ubuntu", {}))
    _save_state(Ubuntu={"found": {}, "found_at": time.time() - 120})
    generic_agent.redetect_wsl_agents()
    assert len(calls) == 1
    assert generic_agent._wsl_cache[1] == ("Ubuntu", {"codex": "codex"})

    calls.clear()
    monkeypatch.setattr(generic_agent, "wsl_distro_running", lambda d: False)
    _save_state(Ubuntu={"found": {}, "found_at": 1})
    generic_agent.redetect_wsl_agents()
    assert calls == []


def test_running_check_reads_the_utf16_listing_without_starting_wsl(monkeypatch):
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        out = "\ufeffUbuntu\r\ndocker-desktop\r\n".encode("utf-16-le")
        return type("P", (), {"stdout": out})()

    monkeypatch.setattr(generic_agent.subprocess, "run", fake_run)
    assert generic_agent.wsl_distro_running("ubuntu") is True
    assert generic_agent.wsl_distro_running("Debian") is False
    assert seen[0] == ["wsl.exe", "--list", "--running", "-q"]


def test_running_check_says_stopped_when_nothing_runs(monkeypatch):
    out = "There are no running distributions.\r\n".encode("utf-16-le")
    monkeypatch.setattr(generic_agent.subprocess, "run", lambda cmd, **kw: type("P", (), {"stdout": out})())
    assert generic_agent.wsl_distro_running("Ubuntu") is False


def test_codex_config_of_a_stopped_distro_comes_from_the_saved_copy(monkeypatch):
    calls = _probe_env(monkeypatch, False)
    monkeypatch.setattr(generic_agent, "find_agent_binary", lambda a: None)
    monkeypatch.setattr(generic_agent, "wsl_agents", lambda: ("Ubuntu", {"codex": "codex"}))
    _save_state(Ubuntu={"found": {"codex": "codex"}, "codex_config": 'model = "x"', "codex_config_at": 1})
    assert generic_agent._read_codex_config() == 'model = "x"'
    assert calls == []


def test_codex_config_of_a_running_distro_is_not_reread_while_the_saved_copy_is_recent(monkeypatch):
    calls = _probe_env(monkeypatch, True)
    monkeypatch.setattr(generic_agent, "find_agent_binary", lambda a: None)
    monkeypatch.setattr(generic_agent, "wsl_agents", lambda: ("Ubuntu", {"codex": "codex"}))
    _save_state(Ubuntu={"codex_config": 'model = "x"', "codex_config_at": time.time() - 60})
    assert generic_agent._read_codex_config() == 'model = "x"'
    assert calls == []


def test_codex_config_of_a_running_distro_is_read_and_saved_when_none_is_saved(monkeypatch):
    calls = _probe_env(monkeypatch, True, 'model = "y"')
    monkeypatch.setattr(generic_agent, "find_agent_binary", lambda a: None)
    monkeypatch.setattr(generic_agent, "wsl_agents", lambda: ("Ubuntu", {"codex": "codex"}))
    assert generic_agent._read_codex_config() == 'model = "y"'
    assert len(calls) == 1
    assert _saved()["codex_config"] == 'model = "y"'


def test_codex_config_is_empty_for_a_stopped_distro_that_never_saved_one(monkeypatch):
    calls = _probe_env(monkeypatch, False)
    monkeypatch.setattr(generic_agent, "find_agent_binary", lambda a: None)
    monkeypatch.setattr(generic_agent, "wsl_agents", lambda: ("Ubuntu", {"codex": "codex"}))
    assert generic_agent._read_codex_config() == ""
    assert calls == []


def test_expired_wsl_cache_is_served_stale_while_refreshing_in_the_background(monkeypatch):
    import threading
    import time

    release = threading.Event()
    calls = []

    def slow_probe():
        calls.append(1)
        release.wait(5)
        return "Ubuntu", {"codex": "codex"}

    monkeypatch.setattr(generic_agent, "_wsl_probe", slow_probe)
    monkeypatch.setattr(generic_agent, "_wsl_cache", (time.monotonic() - 1000, (None, {})))
    assert generic_agent.wsl_agents() == (None, {})
    assert generic_agent.wsl_agents() == (None, {})
    release.set()
    for _ in range(50):
        if generic_agent._wsl_cache[1][0] == "Ubuntu":
            break
        time.sleep(0.05)
    assert generic_agent.wsl_agents() == ("Ubuntu", {"codex": "codex"})
    assert len(calls) == 1
