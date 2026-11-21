import generic_agent as ga


def test_windows_resume_commands(monkeypatch):
    monkeypatch.setattr(ga, "find_agent_binary", lambda a: f"C:\\bin\\{a}.exe")
    assert ga.build_resume_command("claude", "C:\\w", "abc-1") == ["C:\\bin\\claude.exe", "--resume", "abc-1"]
    assert ga.build_resume_command("codex", "C:\\w", "019a", extra_args=("-c", "x=1")) == [
        "C:\\bin\\codex.exe", "-c", "x=1", "resume", "019a",
    ]
    assert ga.build_resume_command("crush", "C:\\w", "x") == ["C:\\bin\\crush.exe", "--session", "x"]
    assert ga.build_resume_command("aider", "C:\\w", "x") is None
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


def test_pin_resume_keeps_wsl_and_other_agents_out_of_the_handoff_pin(monkeypatch):
    monkeypatch.setattr(ga, "_pinned_sessions", {})
    monkeypatch.setattr(ga, "_linked_sessions", {})
    ga.pin_resume("claude", ["wsl.exe", "-d", "Ubuntu"], "pty2", "abc-1")
    ga.pin_resume("codex", ["C:\\bin\\codex.exe", "resume", "x"], "pty3", "x")
    assert ga.pinned_session_id("pty2") is None
    assert ga.pinned_session_id("pty3") is None
    assert ga.linked_session_id("pty2") == "abc-1"
    assert ga.linked_session_id("pty3") == "x"


def test_unpin_clears_the_resume_link_and_the_session_lookup(monkeypatch):
    monkeypatch.setattr(ga, "_pinned_sessions", {})
    monkeypatch.setattr(ga, "_linked_sessions", {})
    ga.pin_resume("codex", ["C:\\bin\\codex.exe", "resume", "x"], "pty3", "x")
    assert ga.ptys_for_session("codex", "x") == ["pty3"]
    assert ga.ptys_for_session("claude", "x") == []
    ga.unpin_session("pty3")
    assert ga.linked_session_id("pty3") is None and ga.ptys_for_session("codex", "x") == []


def test_claude_resume_keeps_the_stored_title_as_its_name(monkeypatch):
    monkeypatch.setattr(ga, "find_agent_binary", lambda a: f"C:\\bin\\{a}.exe")
    cmd = ga.build_resume_command("claude", "C:\\w", "abc-1", title="Fix the login bug")
    assert cmd == ["C:\\bin\\claude.exe", "--resume", "abc-1", "-n", "Fix the login bug"]


def test_claude_resume_omits_the_name_when_nothing_usable_is_left(monkeypatch):
    monkeypatch.setattr(ga, "find_agent_binary", lambda a: f"C:\\bin\\{a}.exe")
    plain = ["C:\\bin\\claude.exe", "--resume", "abc-1"]
    assert ga.build_resume_command("claude", "C:\\w", "abc-1", title="") == plain
    assert ga.build_resume_command("claude", "C:\\w", "abc-1", title="  \u200b\x07\n ") == plain


def test_resume_name_strips_invisible_characters_and_caps_the_length():
    assert ga._resume_name("a\x00b\u200bc\u202ed\ue000e") == "abcde"
    assert ga._resume_name("two\nlines\tand gaps") == "two lines and gaps"
    assert ga._resume_name("x" * 500) == "x" * 200
    assert ga._resume_name("y" * 199 + " " + "z" * 50) == "y" * 199


def test_windows_resume_passes_shell_metacharacters_as_one_argument(monkeypatch):
    monkeypatch.setattr(ga, "find_agent_binary", lambda a: f"C:\\bin\\{a}.exe")
    title = "foo; rm -rf ~ 'q' \"d\" $(x) `y` --help"
    cmd = ga.build_resume_command("claude", "C:\\w", "abc-1", title=title)
    assert cmd[-2:] == ["-n", title]


def test_wsl_resume_quotes_the_title_for_bash(monkeypatch):
    import shlex

    monkeypatch.setattr(ga, "wsl_agents", lambda: ("Ubuntu", {"claude": "claude"}))
    title = "foo; rm -rf ~ 'q' \"d\" $(x) `y`"
    cmd = ga.build_resume_command("claude", "/mnt/c/w", "abc-1", source="wsl:Ubuntu", title=title)
    script = cmd[-1]
    assert script.startswith("exec claude --resume abc-1 -n ")
    assert shlex.split(script) == ["exec", "claude", "--resume", "abc-1", "-n", title]


def test_wsl_resume_keeps_extra_args(monkeypatch):
    monkeypatch.setattr(ga, "wsl_agents", lambda: ("Ubuntu", {"claude": "claude"}))
    cmd = ga.build_resume_command(
        "claude", "/mnt/c/w", "abc-1", source="wsl:Ubuntu", extra_args=("--model", "x y"), title="T"
    )
    assert cmd[-1] == "exec claude --model 'x y' --resume abc-1 -n T"


def test_other_agents_never_get_a_name(monkeypatch):
    monkeypatch.setattr(ga, "find_agent_binary", lambda a: f"C:\\bin\\{a}.exe")
    assert ga.build_resume_command("codex", "C:\\w", "019a", title="Anything") == [
        "C:\\bin\\codex.exe", "resume", "019a",
    ]
    assert ga.build_resume_command("crush", "C:\\w", "x", title="Anything") == [
        "C:\\bin\\crush.exe", "--session", "x",
    ]
    monkeypatch.setattr(ga, "wsl_agents", lambda: ("Ubuntu", {"codex": "codex"}))
    cmd = ga.build_resume_command("codex", "/mnt/c/w", "a", source="wsl:Ubuntu", title="Anything")
    assert cmd[-1] == "exec codex resume a"
