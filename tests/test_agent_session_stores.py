import json
import sqlite3

import agent_sessions as ags
import generic_agent


def text_parts(text):
    return json.dumps([{"type": "text", "data": {"text": text}}])


def make_crush(project, sessions, messages=()):
    db = project / ".crush" / "crush.db"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT, title TEXT, "
        "message_count INTEGER, created_at INTEGER, updated_at INTEGER)"
    )
    con.execute("CREATE TABLE messages (id TEXT, session_id TEXT, role TEXT, parts TEXT, created_at INTEGER)")
    con.executemany("INSERT INTO sessions VALUES (?,?,?,?,?,?)", sessions)
    con.executemany("INSERT INTO messages VALUES (?,?,?,?,?)", messages)
    con.commit()
    con.close()
    return db


def make_opencode(home, sessions, messages=(), parts=()):
    db = home / ".local" / "share" / "opencode" / "opencode.db"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE session (id TEXT PRIMARY KEY, parent_id TEXT, directory TEXT, title TEXT, "
        "time_created INTEGER, time_updated INTEGER, time_archived INTEGER)"
    )
    con.execute("CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER, data TEXT)")
    con.execute("CREATE TABLE part (id TEXT, message_id TEXT, session_id TEXT, time_created INTEGER, data TEXT)")
    con.executemany("INSERT INTO session VALUES (?,?,?,?,?,?,?)", sessions)
    con.executemany("INSERT INTO message VALUES (?,?,?,?)", messages)
    con.executemany("INSERT INTO part VALUES (?,?,?,?,?)", parts)
    con.commit()
    con.close()
    return db


def scan(agent, home, cwd, source="windows"):
    return ags._SCANNERS[agent](ags.SourceHome(source, home, str(cwd)))


def test_crush_lists_top_level_sessions_with_messages(tmp_path):
    make_crush(
        tmp_path,
        [
            ("s1", None, "Fix the login bug", 4, 100, 200),
            ("s2", None, "Empty chat", 0, 300, 300),
            ("s3$$toolu_x", "s1", "Subagent", 2, 110, 120),
        ],
    )
    rows = scan("crush", tmp_path, tmp_path)
    assert [r["id"] for r in rows] == ["s1"]
    assert rows[0]["agent"] == "crush"
    assert rows[0]["source"] == "windows"
    assert rows[0]["title"] == "Fix the login bug"
    assert rows[0]["started_at"] == 100
    assert rows[0]["last_active_at"] == 200


def test_crush_untitled_session_takes_its_first_user_message(tmp_path):
    make_crush(
        tmp_path,
        [("s1", None, "New Session", 2, 100, 200)],
        [
            ("m1", "s1", "assistant", text_parts("hello"), 101),
            ("m2", "s1", "user", text_parts("rename the config loader"), 100),
        ],
    )
    assert scan("crush", tmp_path, tmp_path)[0]["title"] == "rename the config loader"


def test_crush_without_a_database_or_with_a_corrupt_one_is_empty(tmp_path):
    assert scan("crush", tmp_path, tmp_path) == []
    (tmp_path / ".crush").mkdir()
    (tmp_path / ".crush" / "crush.db").write_bytes(b"not a database")
    assert scan("crush", tmp_path, tmp_path) == []


def test_crush_ignores_wsl_sources(tmp_path):
    make_crush(tmp_path, [("s1", None, "Fix", 1, 1, 2)])
    assert scan("crush", tmp_path, tmp_path, source="wsl:Ubuntu") == []


def test_opencode_lists_only_this_projects_live_top_level_sessions(tmp_path):
    project = tmp_path / "app"
    project.mkdir()
    here = project.as_posix()
    make_opencode(
        tmp_path,
        [
            ("ses_1", None, here, "Add dark mode", 1_000_000, 2_000_000, None),
            ("ses_2", None, "C:/elsewhere", "Other project", 1_000_000, 2_000_000, None),
            ("ses_3", "ses_1", here, "Subagent", 1_000_000, 2_000_000, None),
            ("ses_4", None, here, "Archived", 1_000_000, 2_000_000, 5),
            ("ses_5", None, here, "No messages", 1_000_000, 2_000_000, None),
        ],
        [(f"m{i}", f"ses_{i}", 1, json.dumps({"role": "user"})) for i in (1, 2, 3, 4)],
    )
    rows = scan("opencode-bare", tmp_path, project)
    assert [r["id"] for r in rows] == ["ses_1"]
    assert rows[0]["agent"] == "opencode-bare"
    assert rows[0]["title"] == "Add dark mode"
    assert rows[0]["started_at"] == 1000
    assert rows[0]["last_active_at"] == 2000


def test_opencode_default_title_is_replaced_by_the_first_user_message(tmp_path):
    project = tmp_path / "app"
    project.mkdir()
    make_opencode(
        tmp_path,
        [("ses_1", None, project.as_posix(), "New session - 2026-11-15T10:00:00.000Z", 1, 2, None)],
        [("m1", "ses_1", 1, json.dumps({"role": "user"}))],
        [("p1", "m1", "ses_1", 1, json.dumps({"type": "text", "text": "wire up the exporter"}))],
    )
    assert scan("opencode-bare", tmp_path, project)[0]["title"] == "wire up the exporter"


def test_opencode_missing_or_corrupt_database_is_empty(tmp_path):
    assert scan("opencode-bare", tmp_path, tmp_path) == []
    db = tmp_path / ".local" / "share" / "opencode" / "opencode.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"not a database")
    assert scan("opencode-bare", tmp_path, tmp_path) == []


def test_scan_project_includes_store_agents_and_worktrees(tmp_path):
    main, wt = tmp_path / "main", tmp_path / "wt"
    main.mkdir()
    wt.mkdir()
    make_crush(wt, [("s1", None, "In a worktree", 1, 1, 2)])
    homes = [ags.SourceHome("windows", tmp_path, str(main)), ags.SourceHome("windows", tmp_path, str(wt))]
    rows = ags.scan_project(str(main), homes=homes)
    assert [(r["agent"], r["id"]) for r in rows] == [("crush", "s1")]
    assert rows[0]["cwd"] == str(wt)


def test_crush_preview_shows_text_only(tmp_path):
    db = make_crush(
        tmp_path,
        [("s1", None, "Chat", 3, 1, 5)],
        [
            ("m1", "s1", "user", text_parts("list the files"), 1),
            ("m2", "s1", "assistant", json.dumps([{"type": "tool_call", "data": {"name": "ls"}}]), 2),
            ("m3", "s1", "assistant", text_parts("There are two files."), 3),
        ],
    )
    rec = {"agent": "crush", "id": "s1", "path": str(db)}
    assert ags.preview(rec) == [
        {"role": "user", "text": "list the files"},
        {"role": "assistant", "text": "There are two files."},
    ]


def test_opencode_preview_shows_text_only(tmp_path):
    db = make_opencode(
        tmp_path,
        [("ses_1", None, "C:/app", "Chat", 1, 5, None)],
        [
            ("m1", "ses_1", 1, json.dumps({"role": "user"})),
            ("m2", "ses_1", 2, json.dumps({"role": "assistant"})),
        ],
        [
            ("p1", "m1", "ses_1", 1, json.dumps({"type": "text", "text": "summarise the repo"})),
            ("p2", "m2", "ses_1", 2, json.dumps({"type": "tool", "state": {}})),
            ("p3", "m2", "ses_1", 3, json.dumps({"type": "text", "text": "It is a web app."})),
        ],
    )
    rec = {"agent": "opencode-bare", "id": "ses_1", "path": str(db)}
    assert ags.preview(rec) == [
        {"role": "user", "text": "summarise the repo"},
        {"role": "assistant", "text": "It is a web app."},
    ]


def test_preview_of_a_vanished_database_raises_oserror(tmp_path):
    rec = {"agent": "crush", "id": "s1", "path": str(tmp_path / "gone.db")}
    try:
        ags.preview(rec)
    except OSError:
        return
    raise AssertionError("expected OSError")


def test_resume_commands(monkeypatch):
    monkeypatch.setattr(generic_agent, "find_agent_binary", lambda agent: f"C:/bin/{agent}.exe")
    assert generic_agent.can_resume("crush") and generic_agent.can_resume("opencode-bare")
    assert not generic_agent.can_resume("aider")
    assert generic_agent.build_resume_command("crush", "C:/app", "s1") == ["C:/bin/crush.exe", "--session", "s1"]
    monkeypatch.setattr("shutil.which", lambda name: "C:/bin/opencode.exe")
    monkeypatch.setattr(generic_agent, "_wrap_windows_cmd", lambda p: p)
    assert generic_agent.build_opencode_bare_command("C:/app") == ["C:/bin/opencode.exe", "C:/app"]
    assert generic_agent.build_opencode_bare_command("C:/app", "ses_1") == [
        "C:/bin/opencode.exe",
        "--session",
        "ses_1",
        "C:/app",
    ]
