"""Agents installed inside WSL are detected and launched through wsl.exe."""

import generic_agent


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
    monkeypatch.setattr(generic_agent.sys, "platform", "win32")
    monkeypatch.setattr(generic_agent.shutil, "which", lambda n: "wsl.exe")
    monkeypatch.setattr(generic_agent, "_wsl_default_distro", lambda: "Ubuntu")
    monkeypatch.setattr(
        generic_agent,
        "_wsl_run",
        lambda args, script=None: "codex=/home/u/.local/bin/codex\npi=/mnt/c/npm/pi\n",
    )
    assert generic_agent._wsl_probe() == ("Ubuntu", {"codex": "codex"})


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
