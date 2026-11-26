import sqlite3

import pytest

import agent_session_index as index


@pytest.fixture(autouse=True)
def _index_path(tmp_path, monkeypatch):
    monkeypatch.setattr(index, "INDEX_PATH", tmp_path / ".gator" / "agent-session-index.db")


def row(path, unit="u1", agent="claude", sid="s1", cwd_key="c:/work/app", last=100.0, mtime_ns=1, size=10):
    return {
        "path": path, "unit": unit, "home": "H", "source": "windows", "agent": agent, "session_id": sid,
        "cwd": "C:\\work\\app", "cwd_key": cwd_key, "title": "t", "branch": "b", "started_at": 1.0,
        "last_active_at": last, "mtime_ns": mtime_ns, "size": size, "preview": "[]",
    }


def test_rows_round_trip_filtered_by_folder_and_newest_first():
    index.apply([row("a", last=1), row("b", sid="s2", last=3), row("c", sid="s3", cwd_key="x")], [])
    assert [r["session_id"] for r in index.rows("windows", "claude", ["c:/work/app"])] == ["s2", "s1"]
    assert index.rows("windows", "codex", ["c:/work/app"]) == []
    assert index.rows("wsl:Ubuntu", "claude", ["c:/work/app"]) == []
    assert [r["path"] for r in index.rows("windows", "claude", ["c:/work/app"], session_id="s1")] == ["a"]
    assert "preview" in index.rows("windows", "claude", ["c:/work/app"], with_preview=True)[0]


def test_known_and_removed_rows():
    index.apply([row("a", mtime_ns=5, size=7), row("b", unit="u2")], [])
    assert index.known("u1") == {"a": (5, 7)}
    assert index.populated() == {"u1", "u2"}
    index.apply([], ["a"])
    assert index.known("u1") == {}


def test_a_row_without_an_agent_is_kept_but_never_listed():
    index.apply([row("sdk", agent="", sid="")], [])
    assert index.known("u1") == {"sdk": (1, 10)}
    assert index.rows("windows", "claude", ["c:/work/app"]) == []


def test_the_index_is_a_wal_database_with_a_schema_version():
    index.apply([row("a")], [])
    con = sqlite3.connect(index.INDEX_PATH)
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert con.execute("PRAGMA user_version").fetchone()[0] == index.VERSION
    con.close()


def test_a_corrupt_file_is_dropped_and_rebuilt():
    index.INDEX_PATH.parent.mkdir(parents=True)
    index.INDEX_PATH.write_bytes(b"this is not a database" * 100)
    assert index.known("u1") == {}
    index.apply([row("a")], [])
    assert index.known("u1") == {"a": (1, 10)}


def test_another_schema_version_is_dropped_and_rebuilt():
    index.apply([row("a")], [])
    con = sqlite3.connect(index.INDEX_PATH)
    con.execute(f"PRAGMA user_version={index.VERSION + 1}")
    con.close()
    assert index.known("u1") == {}
    index.apply([row("b")], [])
    assert list(index.known("u1")) == ["b"]


def test_a_busy_database_is_not_mistaken_for_a_corrupt_one(monkeypatch):
    index.apply([row("a")], [])
    real = sqlite3.connect

    def busy(*a, **kw):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(index.sqlite3, "connect", busy)
    with pytest.raises(sqlite3.OperationalError):
        index.known("u1")
    monkeypatch.setattr(index.sqlite3, "connect", real)
    assert index.known("u1") == {"a": (1, 10)}


def test_a_failed_insert_does_not_delete_the_index():
    index.apply([row("a")], [])
    with pytest.raises(sqlite3.IntegrityError):
        index.apply([{**row("b"), "title": None}], [])
    assert index.known("u1") == {"a": (1, 10)}


def test_only_a_damaged_file_or_another_schema_counts_as_corrupt():
    for exc in (
        sqlite3.IntegrityError("x"), sqlite3.ProgrammingError("x"), sqlite3.DataError("x"),
        sqlite3.OperationalError("database is locked"),
    ):
        assert index._corrupt(exc) is False
    for code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
        exc = sqlite3.DatabaseError("damaged")
        exc.sqlite_errorcode = code
        assert index._corrupt(exc) is True
    assert index._corrupt(index._WrongVersion("another schema")) is True


def test_reading_an_existing_index_does_not_need_the_write_lock():
    index.apply([row("a")], [])
    writer = sqlite3.connect(index.INDEX_PATH)
    writer.execute("BEGIN IMMEDIATE")
    try:
        assert index.known("u1") == {"a": (1, 10)}
        assert [r["path"] for r in index.rows("windows", "claude", ["c:/work/app"])] == ["a"]
        assert index.populated() == {"u1"}
    finally:
        writer.rollback()
        writer.close()


def test_deleted_conversation_text_is_overwritten():
    con = index._open()
    try:
        assert con.execute("PRAGMA secure_delete").fetchone()[0] == 1
    finally:
        con.close()
