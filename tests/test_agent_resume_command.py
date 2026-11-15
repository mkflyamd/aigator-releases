import generic_agent as ga


def test_windows_resume_commands(monkeypatch):
    monkeypatch.setattr(ga, "find_agent_binary", lambda a: f"C:\\bin\\{a}.exe")
    assert ga.build_resume_command("claude", "C:\\w", "abc-1") == ["C:\\bin\\claude.exe", "--resume", "abc-1"]
    assert ga.build_resume_command("codex", "C:\\w", "019a", extra_args=("-c", "x=1")) == [
        "C:\\bin\\codex.exe", "-c", "x=1", "resume", "019a",
    ]
    assert ga.build_resume_command("crush", "C:\\w", "x") is None
    assert ga.build_resume_command("claude", "C:\\w", "abc-1", source="elsewhere") is None


def test_windows_resume_needs_the_binary(monkeypatch):
    monkeypatch.setattr(ga, "find_agent_binary", lambda a: None)
    assert ga.build_resume_command("claude", "C:\\w", "abc-1") is None


def test_wsl_resume_uses_the_sessions_own_distro_and_agent(monkeypatch):
    monkeypatch.setattr(ga, "wsl_agents", lambda: ("Ubuntu", {"claude": "claude"}))
    cmd = ga.build_resume_command("claude", "/mnt/c/work/app", "abc-1", source="wsl:Ubuntu")
    assert cmd == [
        "wsl.exe", "-d", "Ubuntu", "--cd", "/mnt/c/work/app", "--", "bash", "-lc", "exec claude --resume abc-1",
    ]
    assert ga.build_resume_command("claude", "/mnt/c/w", "abc-1", source="wsl:Debian") is None
    assert ga.build_resume_command("codex", "/mnt/c/w", "x", source="wsl:Ubuntu") is None


def test_wsl_resume_quotes_the_id(monkeypatch):
    monkeypatch.setattr(ga, "wsl_agents", lambda: ("Ubuntu", {"codex": "codex"}))
    cmd = ga.build_resume_command("codex", "/mnt/c/w", "a b", source="wsl:Ubuntu")
    assert cmd[-1] == "exec codex resume 'a b'"


def test_pin_resume_records_the_claude_session_id(monkeypatch):
    monkeypatch.setattr(ga, "_pinned_sessions", {})
    cmd = ["C:\\bin\\claude.exe", "--resume", "abc-1"]
    assert ga.pin_resume("claude", cmd, "pty1", "abc-1") == cmd
    assert ga.pinned_session_id("pty1") == "abc-1"


def test_pin_resume_ignores_wsl_and_other_agents(monkeypatch):
    monkeypatch.setattr(ga, "_pinned_sessions", {})
    ga.pin_resume("claude", ["wsl.exe", "-d", "Ubuntu"], "pty2", "abc-1")
    ga.pin_resume("codex", ["C:\\bin\\codex.exe", "resume", "x"], "pty3", "x")
    assert ga.pinned_session_id("pty2") is None
    assert ga.pinned_session_id("pty3") is None
