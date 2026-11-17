from datetime import date

import pytest

from tools import sync_usage_to_mysql as sync


def _item(title="a@amd.com|2026-11-09", **fields):
    return {"fields": {"Title": title, **fields}}


class FakeGraph:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, path, params=None):
        self.calls.append(("get", path, params))
        return self.pages[0]

    def get_absolute(self, url):
        self.calls.append(("absolute", url))
        return self.pages[int(url.rsplit("=", 1)[1])]


class FakeCursor:
    def __init__(self, store):
        self.store = store

    def execute(self, sql, params=None):
        self.store["executed"].append(sql)

    def executemany(self, sql, rows):
        self.store["inserted"].append(list(rows))
        for row in rows:
            self.store["table"].setdefault((row[0], row[1]), row)

    def fetchone(self):
        return (len(self.store["table"]),)


class FakeConnection:
    def __init__(self, table=None):
        self.store = {"executed": [], "inserted": [], "table": dict(table or {}), "commits": 0}

    def cursor(self):
        return FakeCursor(self.store)

    def commit(self):
        self.store["commits"] += 1


def test_row_maps_title_text_and_numbers():
    row = sync.row_from_item(
        _item(
            "A@AMD.com|2026-11-09", OS="Windows", AppVersion="1.2.3", InstallId="abc",
            Messages=5, ToolRuns=2.0, InputTokens="100", Details='{"tools":{"x":1}}',
        )
    )
    assert dict(zip(sync.COLUMNS, row)) == {
        "email": "a@amd.com", "report_date": date(2026, 11, 9),
        "os": "Windows", "app_version": "1.2.3", "install_id": "abc",
        "messages": 5, "tool_runs": 2, "input_tokens": 100, "output_tokens": 0,
        "conversations": 0, "background_tasks": 0, "tool_errors": 0, "mcp_tool_runs": 0,
        "llm_errors": 0, "failovers": 0, "drafts": 0, "avg_turn_ms": 0,
        "details": '{"tools":{"x":1}}',
    }


@pytest.mark.parametrize("title", ["", "no-pipe", "nobody|2026-11-09", "a@amd.com|not-a-date"])
def test_row_skips_bad_titles(title):
    assert sync.row_from_item(_item(title)) is None


def test_row_survives_blank_and_malformed_fields():
    row = dict(zip(sync.COLUMNS, sync.row_from_item(_item(Messages=None, ToolRuns="x", Details="{oops"))))
    assert (row["messages"], row["tool_runs"], row["details"]) == (0, 0, "{}")


def test_fetch_rows_follows_paging_and_counts_skipped():
    gc = FakeGraph(
        [
            {"value": [_item("a@amd.com|2026-11-09"), _item("junk")], "@odata.nextLink": "https://graph/next?page=1"},
            {"value": [_item("b@amd.com|2026-11-09")]},
        ]
    )
    rows, skipped = sync.fetch_rows(gc, "site", "list")
    assert [row[0] for row in rows] == ["a@amd.com", "b@amd.com"]
    assert skipped == 1
    assert gc.calls[0] == ("get", "/sites/site/lists/list/items", {"$expand": "fields", "$top": "200"})
    assert gc.calls[1] == ("absolute", "https://graph/next?page=1")


def test_load_inserts_only_new_rows_and_is_rerunnable():
    rows = [sync.row_from_item(_item(f"{n}@amd.com|2026-11-09")) for n in "ab"]
    connection = FakeConnection()
    assert sync.load(connection, rows, create_table=False) == (0, 2)
    assert sync.load(connection, rows, create_table=False) == (2, 2)
    assert connection.store["commits"] == 2


def test_load_creates_table_only_when_asked():
    plain, with_table = FakeConnection(), FakeConnection()
    sync.load(plain, [], create_table=False)
    sync.load(with_table, [], create_table=True)
    assert not any("CREATE TABLE" in sql for sql in plain.store["executed"])
    assert any("CREATE TABLE" in sql for sql in with_table.store["executed"])


def test_load_chunks_large_batches(monkeypatch):
    monkeypatch.setattr(sync, "INSERT_CHUNK", 2)
    rows = [sync.row_from_item(_item(f"{n}@amd.com|2026-11-09")) for n in "abcde"]
    connection = FakeConnection()
    sync.load(connection, rows, create_table=False)
    assert [len(chunk) for chunk in connection.store["inserted"]] == [2, 2, 1]


def test_insert_never_overwrites_existing_rows():
    assert "ON DUPLICATE KEY UPDATE email = email" in sync.INSERT
    assert sync.INSERT.count("%s") == len(sync.COLUMNS)


def test_schema_has_every_column_and_the_key():
    for column in sync.COLUMNS:
        assert f"  {column} " in sync.SCHEMA
    assert "PRIMARY KEY (email, report_date)" in sync.SCHEMA


def test_dry_run_reads_list_without_password_or_database(monkeypatch, capsys):
    monkeypatch.delenv("AIGATOR_USAGE_DB_PASSWORD", raising=False)
    monkeypatch.setattr(sync, "_graph_client", lambda: FakeGraph([{"value": [_item(), _item("junk")]}]))
    monkeypatch.setattr(sync, "_connect", lambda args: pytest.fail("dry run must not connect"))
    assert sync.main(["--site", "s", "--list", "l", "--dry-run"]) == 0
    assert "Read 1 rows (1 users, 2026-11-09 to 2026-11-09); skipped 1" in capsys.readouterr().out


def test_sync_needs_a_password(monkeypatch, capsys):
    monkeypatch.delenv("AIGATOR_USAGE_DB_PASSWORD", raising=False)
    assert sync.main(["--site", "s", "--list", "l"]) == 2
    assert "AIGATOR_USAGE_DB_PASSWORD" in capsys.readouterr().err


def test_sync_end_to_end_reports_new_rows(monkeypatch, capsys):
    connection = FakeConnection()
    monkeypatch.setenv("AIGATOR_USAGE_DB_PASSWORD", "aigator-fake-api-key")
    monkeypatch.setattr(sync, "_graph_client", lambda: FakeGraph([{"value": [_item()]}]))
    monkeypatch.setattr(sync, "_connect", lambda args: connection)
    connection.close = lambda: None
    assert sync.main(["--site", "s", "--list", "l"]) == 0
    assert "0 -> 1 rows (1 new)" in capsys.readouterr().out
