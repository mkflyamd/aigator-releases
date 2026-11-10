"""Daily usage report: counts come from tasks.db, rows go to a SharePoint list through Graph."""

import base64
import json
import sqlite3
from datetime import date

import pytest

import usage_report

TODAY = date(2026, 11, 10)
CFG = {"usage_list_site_id": "aigator-fake-site", "usage_list_id": "aigator-fake-list"}


def _token(claims: dict) -> str:
    def b64(obj) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'none'})}.{b64(claims)}.sig"


class GraphError(Exception):
    def __init__(self, status_code: int, message: str = ""):
        super().__init__(message or f"Graph API {status_code}")
        self.status_code = status_code


class FakeGraph:
    def __init__(self, email="Jane.Doe@amd.com", token=None):
        self.token = _token({"upn": email, "name": "Jane Doe"}) if token is None else token
        self.posts: list[tuple[str, dict]] = []
        self.gets: list[str] = []
        self.post_errors: list[Exception] = []

    def get_token(self):
        return self.token

    def post(self, path, body):
        if self.post_errors:
            raise self.post_errors.pop(0)
        self.posts.append((path, body))
        return {"id": str(len(self.posts))}

    def get(self, path, **kw):
        self.gets.append(path)
        return {}


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "tasks.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE usage_log (id INTEGER PRIMARY KEY, source TEXT, "
        "input_tokens INTEGER, output_tokens INTEGER, created_at TEXT)"
    )
    con.execute(
        "CREATE TABLE tool_call_log (id INTEGER PRIMARY KEY, created_at TEXT, tool_name TEXT, "
        "is_mcp INTEGER DEFAULT 0, outcome TEXT DEFAULT 'success', error_code TEXT)"
    )
    con.execute(
        "CREATE TABLE turn_log (id INTEGER PRIMARY KEY, context_id TEXT, provider TEXT, model TEXT, "
        "llm_error TEXT, failover_used INTEGER DEFAULT 0, duration_ms INTEGER, active_skills TEXT, created_at TEXT)"
    )
    con.execute("CREATE TABLE tasks (task_id INTEGER PRIMARY KEY, created_at TEXT)")
    con.execute("CREATE TABLE task_drafts (draft_id INTEGER PRIMARY KEY, created_at TEXT)")
    con.commit()
    con.close()
    monkeypatch.setattr(usage_report, "TASKS_DB", db)
    monkeypatch.setattr(usage_report, "STATE_FILE", tmp_path / "usage_report.json")
    graph = FakeGraph()
    monkeypatch.setattr(usage_report, "_graph_client", lambda: graph)
    monkeypatch.setattr(usage_report, "_app_version", lambda: "9.9.9")
    monkeypatch.setattr(usage_report, "_builtin_skills", lambda: {"teams", "email"})
    return db, graph


def _add(db, table, day, n=1, source="chat"):
    con = sqlite3.connect(db)
    for i in range(n):
        ts = f"{day}T10:0{i % 10}:00.000000+00:00"
        if table == "usage_log":
            con.execute("INSERT INTO usage_log (source, created_at) VALUES (?, ?)", (source, ts))
        else:
            con.execute("INSERT INTO tool_call_log (created_at, tool_name) VALUES (?, 'x')", (ts,))
    con.commit()
    con.close()


def _sql(db, sql, rows):
    con = sqlite3.connect(db)
    con.executemany(sql, rows)
    con.commit()
    con.close()


async def test_sends_one_row_per_active_past_day(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 3)
    _add(db, "tool_call_log", "2026-11-08", 2)
    sent = await usage_report.report_pending(CFG, today=TODAY)
    assert sent == 1
    path, body = graph.posts[0]
    assert path == "/sites/aigator-fake-site/lists/aigator-fake-list/items"
    f = body["fields"]
    assert f["Title"] == "jane.doe@amd.com|2026-11-08"
    assert f["Email"] == "jane.doe@amd.com"
    assert f["ReportDate"] == "2026-11-08"
    assert f["Messages"] == 3
    assert f["ToolRuns"] == 2
    assert f["AppVersion"] == "9.9.9"
    assert f["OS"] in ("Windows", "macOS", "Linux")
    assert f["InstallId"]


async def test_messages_count_chat_sources_only(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 2, source="chat")
    _add(db, "usage_log", "2026-11-08", 1, source="chat-direct")
    _add(db, "usage_log", "2026-11-08", 5, source="background")
    await usage_report.report_pending(CFG, today=TODAY)
    assert graph.posts[0][1]["fields"]["Messages"] == 3


async def test_tool_runs_alone_make_a_day_active(env):
    db, graph = env
    _add(db, "tool_call_log", "2026-11-08", 4)
    assert await usage_report.report_pending(CFG, today=TODAY) == 1
    f = graph.posts[0][1]["fields"]
    assert (f["Messages"], f["ToolRuns"]) == (0, 4)


async def test_background_only_day_is_not_active(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 5, source="background")
    assert await usage_report.report_pending(CFG, today=TODAY) == 0
    assert graph.posts == []


async def test_today_is_not_sent(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-10", 2)
    assert await usage_report.report_pending(CFG, today=TODAY) == 0
    assert graph.posts == []


async def test_a_sent_day_is_not_sent_again(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 1)
    await usage_report.report_pending(CFG, today=TODAY)
    await usage_report.report_pending(CFG, today=TODAY)
    assert len(graph.posts) == 1


async def test_duplicate_key_response_marks_day_sent(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 1)
    graph.post_errors = [GraphError(400, "The field Title must be unique: duplicate value")]
    assert await usage_report.report_pending(CFG, today=TODAY) == 0
    await usage_report.report_pending(CFG, today=TODAY)
    assert graph.posts == []


async def test_failure_leaves_day_pending_for_next_run(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 1)
    graph.post_errors = [GraphError(503, "unavailable")]
    assert await usage_report.report_pending(CFG, today=TODAY) == 0
    assert await usage_report.report_pending(CFG, today=TODAY) == 1


async def test_day_older_than_seven_days_is_dropped(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-02", 1)
    assert await usage_report.report_pending(CFG, today=TODAY) == 0
    assert graph.posts == []


async def test_forbidden_opens_the_share_link_then_retries_once(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 1)
    graph.post_errors = [GraphError(403, "Access denied")]
    cfg = {**CFG, "usage_list_link": "https://example.invalid/aigator-fake-link"}
    assert await usage_report.report_pending(cfg, today=TODAY) == 1
    assert len(graph.gets) == 1 and graph.gets[0].startswith("/shares/u!") and graph.gets[0].endswith("/list")


async def test_forbidden_without_a_link_is_a_plain_failure(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 1)
    graph.post_errors = [GraphError(403, "Access denied")]
    cfg = {**CFG, "usage_list_link": ""}
    assert await usage_report.report_pending(cfg, today=TODAY) == 0
    assert graph.gets == []


async def test_without_a_microsoft_identity_nothing_is_sent(env):
    db, graph = env
    graph.token = ""
    _add(db, "usage_log", "2026-11-08", 1)
    assert await usage_report.report_pending(CFG, today=TODAY) == 0
    assert graph.posts == []


async def test_unset_list_ids_disable_reporting(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 1)
    assert await usage_report.report_pending({"usage_list_site_id": "", "usage_list_id": ""}, today=TODAY) == 0
    assert graph.posts == []


async def test_reporting_is_off_without_config(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 1)
    assert await usage_report.report_pending({}, today=TODAY) == 0
    assert await usage_report.report_pending(None, today=TODAY) == 0
    assert graph.posts == []


def test_is_enabled_needs_both_ids():
    assert usage_report.is_enabled(CFG)
    assert not usage_report.is_enabled({})
    assert not usage_report.is_enabled({"usage_list_site_id": "aigator-fake-site"})


async def test_missing_tool_table_still_reports_messages(env):
    db, graph = env
    con = sqlite3.connect(db)
    con.execute("DROP TABLE tool_call_log")
    con.commit()
    con.close()
    _add(db, "usage_log", "2026-11-08", 2)
    assert await usage_report.report_pending(CFG, today=TODAY) == 1
    assert graph.posts[0][1]["fields"]["ToolRuns"] == 0


async def test_install_id_is_stable_across_runs(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 1)
    _add(db, "usage_log", "2026-11-09", 1)
    await usage_report.report_pending(CFG, today=TODAY)
    ids = {body["fields"]["InstallId"] for _, body in graph.posts}
    assert len(graph.posts) == 2 and len(ids) == 1


async def test_payload_has_only_the_expected_columns(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 1)
    await usage_report.report_pending(CFG, today=TODAY)
    assert set(graph.posts[0][1]["fields"]) == {
        "Title", "Email", "ReportDate", "OS", "AppVersion", "InstallId", "Messages", "ToolRuns",
        "InputTokens", "OutputTokens", "Conversations", "BackgroundTasks", "ToolErrors",
        "McpToolRuns", "LlmErrors", "Failovers", "Drafts", "AvgTurnMs", "Details",
    }


D8 = "2026-11-08T10:00:00.000000+00:00"


async def test_token_sums_include_every_source(env):
    db, graph = env
    _sql(db, "INSERT INTO usage_log (source, input_tokens, output_tokens, created_at) VALUES (?, ?, ?, ?)", [
        ("chat", 100, 10, D8),
        ("background", 50, 5, D8),
        ("chat", 7, 1, "2026-11-09T10:00:00.000000+00:00"),
    ])
    await usage_report.report_pending(CFG, today=TODAY)
    f = graph.posts[0][1]["fields"]
    assert (f["InputTokens"], f["OutputTokens"]) == (150, 15)


async def test_turn_signals(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 1)
    _sql(db, "INSERT INTO turn_log (context_id, provider, model, llm_error, failover_used, duration_ms, "
             "active_skills, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
        ("c1", "P", "m1", None, 0, 100, "[]", D8),
        ("c1", "P", "m1", "boom", 1, 200, "[]", D8),
        ("c2", "P", "m2", "", 0, 300, "[]", D8),
    ])
    await usage_report.report_pending(CFG, today=TODAY)
    f = graph.posts[0][1]["fields"]
    assert f["Conversations"] == 2
    assert f["LlmErrors"] == 1
    assert f["Failovers"] == 1
    assert f["AvgTurnMs"] == 200


async def test_background_tasks_and_drafts_count_for_their_day(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 1)
    _sql(db, "INSERT INTO tasks (task_id, created_at) VALUES (?, ?)", [
        (1, D8), (2, D8), (3, "2026-11-07T10:00:00.000000+00:00"),
    ])
    _sql(db, "INSERT INTO task_drafts (draft_id, created_at) VALUES (?, ?)", [(1, D8)])
    await usage_report.report_pending(CFG, today=TODAY)
    f = graph.posts[0][1]["fields"]
    assert (f["BackgroundTasks"], f["Drafts"]) == (2, 1)


async def test_tool_errors_count_only_error_outcome_and_mcp_runs_are_counted(env):
    db, graph = env
    _sql(db, "INSERT INTO tool_call_log (created_at, tool_name, is_mcp, outcome, error_code) VALUES (?, ?, ?, ?, ?)", [
        (D8, "read_file", 0, "success", None),
        (D8, "read_file", 0, "error", "tool_error"),
        (D8, "run_python", 0, "cancelled", None),
        (D8, "srv_tool", 1, "success", None),
        (D8, "srv_tool", 1, "error", "mcp_error"),
    ])
    await usage_report.report_pending(CFG, today=TODAY)
    f = graph.posts[0][1]["fields"]
    assert (f["ToolRuns"], f["ToolErrors"], f["McpToolRuns"]) == (5, 2, 2)


async def test_signal_only_day_is_not_active(env):
    db, graph = env
    _sql(db, "INSERT INTO turn_log (context_id, provider, model, created_at) VALUES (?, ?, ?, ?)", [("c1", "P", "m1", D8)])
    _sql(db, "INSERT INTO tasks (task_id, created_at) VALUES (?, ?)", [(1, D8)])
    _sql(db, "INSERT INTO task_drafts (draft_id, created_at) VALUES (?, ?)", [(1, D8)])
    assert await usage_report.report_pending(CFG, today=TODAY) == 0
    assert graph.posts == []


async def test_missing_signal_tables_give_zeros(env):
    db, graph = env
    con = sqlite3.connect(db)
    for table in ("turn_log", "tasks", "task_drafts"):
        con.execute(f"DROP TABLE {table}")
    con.commit()
    con.close()
    _add(db, "usage_log", "2026-11-08", 2)
    assert await usage_report.report_pending(CFG, today=TODAY) == 1
    f = graph.posts[0][1]["fields"]
    assert f["Messages"] == 2
    for name in ("Conversations", "BackgroundTasks", "LlmErrors", "Failovers", "Drafts", "AvgTurnMs"):
        assert f[name] == 0


async def test_legacy_tool_table_without_new_columns_gives_zeros(env):
    db, graph = env
    con = sqlite3.connect(db)
    con.execute("DROP TABLE tool_call_log")
    con.execute("CREATE TABLE tool_call_log (id INTEGER PRIMARY KEY, created_at TEXT, tool_name TEXT)")
    con.commit()
    con.close()
    _add(db, "tool_call_log", "2026-11-08", 3)
    assert await usage_report.report_pending(CFG, today=TODAY) == 1
    f = graph.posts[0][1]["fields"]
    assert (f["ToolRuns"], f["ToolErrors"], f["McpToolRuns"]) == (3, 0, 0)


def _details(graph):
    return json.loads(graph.posts[0][1]["fields"]["Details"])


async def test_details_break_down_models_and_skills(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 1)
    _sql(db, "INSERT INTO turn_log (context_id, provider, model, active_skills, created_at) VALUES (?, ?, ?, ?, ?)", [
        ("c1", "P", "m1", json.dumps(["teams", "email"]), D8),
        ("c1", "P", "m1", json.dumps(["teams", "my-private-skill"]), D8),
        ("c2", "P", "m2", "[]", D8),
        ("c3", "", "", "[]", D8),
    ])
    await usage_report.report_pending(CFG, today=TODAY)
    d = _details(graph)
    assert d["models"] == {"P/m1": 2, "P/m2": 1}
    assert d["skills"] == {"teams": 2, "email": 1, "custom": 1}


async def test_details_break_down_tools_and_errors(env):
    db, graph = env
    _sql(db, "INSERT INTO tool_call_log (created_at, tool_name, is_mcp, outcome, error_code) VALUES (?, ?, ?, ?, ?)", [
        (D8, "read_file", 0, "success", None),
        (D8, "read_file", 0, "error", "tool_error"),
        (D8, "run_python", 0, "cancelled", None),
        (D8, "srv_tool", 1, "success", None),
        (D8, "srv_tool", 1, "error", "mcp_error"),
        (D8, "<tool>", 0, "error", "<tool>"),
    ])
    await usage_report.report_pending(CFG, today=TODAY)
    d = _details(graph)
    assert d["tools"] == {"read_file": 2, "run_python": 1, "mcp": 2}
    assert d["errors"] == {"tool_error": 1, "mcp_error": 1}


async def test_details_never_name_user_added_skills_or_mcp_tools(env):
    db, graph = env
    _sql(db, "INSERT INTO tool_call_log (created_at, tool_name, is_mcp) VALUES (?, ?, ?)", [(D8, "private_srv_tool", 1)])
    _sql(db, "INSERT INTO turn_log (context_id, provider, model, active_skills, created_at) VALUES (?, ?, ?, ?, ?)", [
        ("c1", "P", "m1", json.dumps(["my-private-skill"]), D8),
    ])
    await usage_report.report_pending(CFG, today=TODAY)
    text = graph.posts[0][1]["fields"]["Details"]
    assert "private" not in text


async def test_details_list_only_the_top_ten_tools(env):
    db, graph = env
    rows = [(D8, f"t{i:02d}", 0) for i in range(12) for _ in range(12 - i)]
    _sql(db, "INSERT INTO tool_call_log (created_at, tool_name, is_mcp) VALUES (?, ?, ?)", rows)
    await usage_report.report_pending(CFG, today=TODAY)
    tools = _details(graph)["tools"]
    assert len(tools) == 10
    assert "t00" in tools and "t10" not in tools and "t11" not in tools


async def test_details_are_empty_objects_when_there_is_nothing_to_break_down(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 1)
    await usage_report.report_pending(CFG, today=TODAY)
    assert graph.posts[0][1]["fields"]["Details"] == '{"errors":{},"models":{},"skills":{},"tools":{}}'
