"""Focused tests for the managed production log primitives."""
import logging
import os
import time

import logging_setup


def _record(message: str) -> logging.LogRecord:
    return logging.makeLogRecord({"name": "test", "levelno": logging.INFO, "msg": message})


def test_strict_rotation_never_exceeds_the_limit(tmp_path):
    log_path = tmp_path / "gator_backend.log"
    handler = logging_setup.StrictRotatingFileHandler(log_path, max_bytes=10)
    handler.setFormatter(logging.Formatter("%(message)s"))
    try:
        handler.emit(_record("abcdefghijklmno"))
        handler.emit(_record("123456789"))
    finally:
        handler.close()

    retained = [log_path, log_path.with_suffix(".1.log")]
    assert all(path.stat().st_size <= 10 for path in retained if path.exists())
    assert log_path.exists()
    assert log_path.with_suffix(".1.log").exists()


def test_cleanup_old_logs_removes_only_expired_files(tmp_path, monkeypatch):
    active = tmp_path / "gator_backend.log"
    backup = tmp_path / "gator_backend.1.log"
    active.write_text("old")
    backup.write_text("new")
    now = time.time()
    os.utime(active, (now - 31 * 24 * 60 * 60, now - 31 * 24 * 60 * 60))
    monkeypatch.setattr(logging_setup, "LOG_FILE", active)
    monkeypatch.setattr(logging_setup, "LEGACY_LOG_FILE", tmp_path / "aigator.log")

    assert logging_setup.cleanup_old_logs(now=now) == 1
    assert not active.exists()
    assert backup.exists()


def test_non_blocking_queue_handler_drops_when_full():
    handler = logging_setup._NonBlockingQueueHandler(logging_setup.queue.Queue(maxsize=1))
    handler.enqueue(_record("first"))
    handler.enqueue(_record("second"))
    assert handler.dropped_records == 1


def test_existing_oversized_logs_are_normalized(tmp_path):
    log_path = tmp_path / "gator_backend.log"
    backup = log_path.with_suffix(".1.log")
    log_path.write_bytes(b"a" * 25)
    backup.write_bytes(b"b" * 18)

    handler = logging_setup.StrictRotatingFileHandler(log_path, max_bytes=10)
    handler.close()

    assert log_path.stat().st_size <= 10
    assert backup.stat().st_size <= 10


def test_rotation_preserves_valid_utf8_files(tmp_path):
    log_path = tmp_path / "gator_backend.log"
    log_path.write_text("abc", encoding="utf-8")
    handler = logging_setup.StrictRotatingFileHandler(log_path, max_bytes=7)
    handler.setFormatter(logging.Formatter("%(message)s"))
    try:
        handler.emit(_record("😀"))
    finally:
        handler.close()

    assert log_path.read_text(encoding="utf-8") == "😀\n"
    assert log_path.with_suffix(".1.log").read_text(encoding="utf-8") == "abc"


def test_oversized_record_is_truncated_within_cap(tmp_path):
    log_path = tmp_path / "gator_backend.log"
    handler = logging_setup.StrictRotatingFileHandler(log_path, max_bytes=64)
    handler.setFormatter(logging.Formatter("%(message)s"))
    try:
        handler.emit(_record("😀" * 100))
    finally:
        handler.close()

    assert log_path.stat().st_size <= 64
    text = log_path.read_text(encoding="utf-8")
    assert "[log record truncated]" in text


def test_legacy_logs_are_renamed_and_bounded(tmp_path, monkeypatch):
    legacy = tmp_path / "aigator.log"
    current = tmp_path / "gator_backend.log"
    legacy.write_bytes(b"x" * 20)
    monkeypatch.setattr(logging_setup, "LEGACY_LOG_FILE", legacy)
    monkeypatch.setattr(logging_setup, "LOG_FILE", current)

    logging_setup.migrate_legacy_logs(max_bytes=10)

    assert not legacy.exists()
    assert current.exists()
    assert current.stat().st_size <= 10


def test_file_write_failure_is_contained(tmp_path, monkeypatch):
    handler = logging_setup.StrictRotatingFileHandler(
        tmp_path / "gator_backend.log", max_bytes=64
    )
    handled = []
    monkeypatch.setattr(handler, "_open", lambda: (_ for _ in ()).throw(OSError("disk unavailable")))
    monkeypatch.setattr(handler, "handleError", lambda record: handled.append(record))

    handler.emit(_record("user operation continues"))

    assert len(handled) == 1


def test_running_listener_safely_expires_old_active_log(tmp_path, monkeypatch):
    active = tmp_path / "gator_backend.log"
    active.write_text("old", encoding="utf-8")
    now = time.time()
    os.utime(active, (now - 31 * 24 * 60 * 60, now - 31 * 24 * 60 * 60))
    handler = logging_setup.StrictRotatingFileHandler(active, max_bytes=64)
    monkeypatch.setattr(logging_setup, "LOG_FILE", active)
    monkeypatch.setattr(logging_setup, "LEGACY_LOG_FILE", tmp_path / "aigator.log")
    monkeypatch.setattr(logging_setup, "_listener", object())
    monkeypatch.setattr(logging_setup, "_file_handler", handler)
    try:
        assert logging_setup.cleanup_old_logs(now=now) == 1
        assert active.read_bytes() == b""
    finally:
        handler.close()
