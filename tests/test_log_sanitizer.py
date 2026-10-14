import logging
import os
import sys
from pathlib import Path

import pytest

import logging_setup
from log_sanitizer import sanitize


def test_secrets_in_key_value_and_bearer_form_are_redacted():
    text = "401 for api_key=aigator-fake-api-key and Authorization: Bearer aigator-fake-api-key"
    out = sanitize(text)
    assert "aigator-fake-api-key" not in out
    assert out.count("[redacted]") == 2


def test_home_and_user_directories_are_masked():
    home = str(Path.home())
    out = sanitize(f"open {home}{os.sep}notes.txt failed")
    assert out.startswith("open ~") and home not in out
    out = sanitize(r"C:\Users\someone\x and /home/other/y")
    assert "someone" not in out and "other" not in out


def test_plain_text_and_empty_values_are_unchanged():
    assert sanitize("tool timed out after 30s") == "tool timed out after 30s"
    assert sanitize("") == ""
    assert sanitize(None) is None


def test_log_handler_writes_sanitized_text(tmp_path):
    handler = logging_setup.StrictRotatingFileHandler(tmp_path / "gator_backend.log")
    handler.setFormatter(logging.Formatter("%(message)s"))
    try:
        handler.emit(logging.makeLogRecord({"name": "t", "levelno": logging.INFO, "msg": "token=aigator-fake-api-key"}))
    finally:
        handler.close()
    assert b"aigator-fake-api-key" not in (tmp_path / "gator_backend.log").read_bytes()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_log_file_and_directory_are_owner_only(tmp_path):
    handler = logging_setup.StrictRotatingFileHandler(tmp_path / "logs" / "gator_backend.log")
    handler.setFormatter(logging.Formatter("%(message)s"))
    try:
        handler.emit(logging.makeLogRecord({"name": "t", "levelno": logging.INFO, "msg": "x"}))
    finally:
        handler.close()
    assert (tmp_path / "logs" / "gator_backend.log").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "logs").stat().st_mode & 0o777 == 0o700


def test_tenant_ids_and_internal_hostnames_are_removed_in_every_mode(monkeypatch):
    monkeypatch.setenv("AIGATOR_PRIVACY_MODE", "0")
    out = sanitize(
        "login.microsoftonline.com/11111111-2222-3333-4444-555555555555 failed for host build01.corp.amd.com "
        r"and \\fileserver\share, turn 11111111-2222-3333-4444-555555555555"
    )
    assert "<tenant>" in out and "build01" not in out and "fileserver" not in out
    assert out.count("11111111-2222") == 1  # a plain GUID (for example a turn id) stays for debugging


def test_privacy_mode_removes_paths_tool_names_and_guids(monkeypatch):
    monkeypatch.setenv("AIGATOR_PRIVACY_MODE", "1")
    out = sanitize(r"mcp__crm__lookup failed in C:\Projects\Apollo\notes.txt and /srv/apollo/data.csv id 11111111-2222-3333-4444-555555555555")
    assert "crm" not in out and "Apollo" not in out and "apollo" not in out and "11111111" not in out
    assert "failed" in out


def test_privacy_mode_defaults_on_for_packaged_builds(monkeypatch):
    import log_sanitizer

    monkeypatch.delenv("AIGATOR_PRIVACY_MODE", raising=False)
    monkeypatch.setattr(log_sanitizer, "_cached_privacy", None)
    monkeypatch.setenv("AIGATOR_MANAGED_LOGGING", "1")
    assert log_sanitizer.privacy_mode() is True
