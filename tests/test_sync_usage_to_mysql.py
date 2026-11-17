from datetime import date

import pytest

from tools import sync_usage_to_mysql as sync


def _item(title="a@amd.com|2026-11-09", creator=None, **fields):
    creator = creator if creator is not None else title.rpartition("|")[0]
    return {"createdBy": {"user": {"email": creator}}, "fields": {"Title": title, **fields}}


def _row(item):
    user = sync._creator(item)
    return sync.row_from_item(item, {str(user.get("email") or "").lower()} - {""})


class FakeGraph:
    def __init__(self, pages, profiles=None):
        self.pages = pages
        self.profiles = profiles or {}
        self.calls = []

    def get(self, path, params=None):
        self.calls.append(("get", path, params))
        if path.startswith("/users/"):
            return self.profiles[path.rsplit("/", 1)[1]]
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
    row = _row(
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
    assert _row(_item(title)) is None


def test_row_accepts_creator_with_different_letter_case():
    assert _row(_item("a@amd.com|2026-11-09", creator="A@AMD.com")) is not None


def test_row_skips_title_email_that_is_not_the_creator():
    assert _row(_item("victim@amd.com|2026-11-09", creator="attacker@amd.com")) is None


@pytest.mark.parametrize("created_by", [None, {}, {"user": {}}, {"application": {"displayName": "x"}}])
def test_row_skips_items_without_a_creator_email(created_by):
    item = _item()
    item["createdBy"] = created_by
    assert _row(item) is None


def test_creator_addresses_include_sign_in_name_mail_and_smtp_aliases_once_per_user():
    profile = {
        "userPrincipalName": "Alias@amd.com",
        "mail": "First.Last@amd.com",
        "proxyAddresses": ["x500:/o=x", "smtp:old@amd.com", "SMTP:First.Last@amd.com"],
    }
    gc = FakeGraph([], {"u1": profile})
    user = {"id": "u1", "email": "First.Last@amd.com"}
    cache = {}
    assert sync.creator_addresses(gc, user, cache) == {"alias@amd.com", "first.last@amd.com", "old@amd.com"}
    sync.creator_addresses(gc, user, cache)
    assert [call[1] for call in gc.calls] == ["/users/u1"]


def test_row_accepts_title_with_sign_in_name_when_creator_mail_differs():
    item = _item("alias@amd.com|2026-11-09", creator="first.last@amd.com")
    item["createdBy"]["user"]["id"] = "u1"
    gc = FakeGraph([{"value": [item]}], {"u1": {"userPrincipalName": "alias@amd.com", "mail": "first.last@amd.com"}})
    rows, skipped = sync.fetch_rows(gc, "site", "list")
    assert [row[0] for row in rows] == ["alias@amd.com"] and skipped == 0


def test_failed_profile_lookup_keeps_only_the_creator_mail():
    class Failing(FakeGraph):
        def get(self, path, params=None):
            if path.startswith("/users/"):
                raise RuntimeError("403")
            return super().get(path, params)

    alias = _item("alias@amd.com|2026-11-09", creator="first.last@amd.com")
    own = _item("first.last@amd.com|2026-11-09")
    for item in (alias, own):
        item["createdBy"]["user"] = {"id": "u1", "email": "first.last@amd.com"}
    rows, skipped = sync.fetch_rows(Failing([{"value": [alias, own]}]), "site", "list")
    assert [row[0] for row in rows] == ["first.last@amd.com"] and skipped == 1


def test_repeat_title_in_one_batch_keeps_the_first_values():
    first, second = _item(Messages=1), _item(Messages=9)
    rows, _ = sync.fetch_rows(FakeGraph([{"value": [first, second]}]), "site", "list")
    connection = FakeConnection()
    sync.load(connection, rows, create_table=False)
    assert [row[sync.COLUMNS.index("messages")] for row in connection.store["table"].values()] == [1]


def test_overflowing_and_non_finite_values_load_as_zero_and_empty():
    row = dict(zip(sync.COLUMNS, _row(_item(Messages=float("inf"), Details='{"a": NaN}'))))
    assert (row["messages"], row["details"]) == (0, "{}")


def test_password_cannot_be_passed_as_a_flag():
    with pytest.raises(SystemExit):
        sync.main(["--site", "s", "--list", "l", "--db-password", "aigator-fake-api-key"])


def test_sync_needs_database_host_user_and_name(monkeypatch, capsys):
    for name in ("HOST", "USER", "NAME"):
        monkeypatch.delenv(f"AIGATOR_USAGE_DB_{name}", raising=False)
    monkeypatch.setenv("AIGATOR_USAGE_DB_PASSWORD", "aigator-fake-api-key")
    assert sync.main(["--site", "s", "--list", "l"]) == 2
    assert "AIGATOR_USAGE_DB_HOST" in capsys.readouterr().err


def test_row_survives_blank_and_malformed_fields():
    row = dict(zip(sync.COLUMNS, _row(_item(Messages=None, ToolRuns="x", Details="{oops"))))
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
    rows = [_row(_item(f"{n}@amd.com|2026-11-09")) for n in "ab"]
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
    rows = [_row(_item(f"{n}@amd.com|2026-11-09")) for n in "abcde"]
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
    assert sync.main(["--site", "s", "--list", "l", "--db-host", "h", "--db-user", "u", "--db-name", "d"]) == 2
    assert "AIGATOR_USAGE_DB_PASSWORD" in capsys.readouterr().err


def test_sync_end_to_end_reports_new_rows(monkeypatch, capsys):
    connection = FakeConnection()
    monkeypatch.setenv("AIGATOR_USAGE_DB_PASSWORD", "aigator-fake-api-key")
    monkeypatch.setattr(sync, "_graph_client", lambda: FakeGraph([{"value": [_item()]}]))
    monkeypatch.setattr(sync, "_connect", lambda args: connection)
    connection.close = lambda: None
    assert sync.main(["--site", "s", "--list", "l", "--db-host", "h", "--db-user", "u", "--db-name", "d"]) == 0
    assert "0 -> 1 rows (1 new)" in capsys.readouterr().out
