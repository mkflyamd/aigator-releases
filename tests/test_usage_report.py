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
    con.execute("CREATE TABLE usage_log (id INTEGER PRIMARY KEY, source TEXT, created_at TEXT)")
    con.execute("CREATE TABLE tool_call_log (id INTEGER PRIMARY KEY, created_at TEXT, tool_name TEXT)")
    con.commit()
    con.close()
    monkeypatch.setattr(usage_report, "TASKS_DB", db)
    monkeypatch.setattr(usage_report, "STATE_FILE", tmp_path / "usage_report.json")
    graph = FakeGraph()
    monkeypatch.setattr(usage_report, "_graph_client", lambda: graph)
    monkeypatch.setattr(usage_report, "_app_version", lambda: "9.9.9")
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
    }
