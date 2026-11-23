import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest

import google_accounts as ga


def test_normalize_accounts_lowercases_dedupes_and_drops_empties():
    assert ga.normalize_accounts([" A@Example.test ", "", "a@example.test", "b@example.test", None]) == [
        "a@example.test",
        "b@example.test",
    ]
    assert ga.normalize_accounts(None) == []


def test_is_valid_email():
    assert ga.is_valid_email("a@example.test")
    assert not ga.is_valid_email("not-an-email")
    assert not ga.is_valid_email("a b@example.test")


def test_configured_accounts_prefers_list_then_legacy_single_email():
    assert ga.configured_accounts({"google_accounts": ["A@example.test", "b@example.test"]}) == [
        "a@example.test",
        "b@example.test",
    ]
    assert ga.configured_accounts({"google_user_email": "Old@Example.test"}) == ["old@example.test"]
    assert ga.configured_accounts({}) == []


def test_configured_accounts_empty_list_wins_over_stale_single_email():
    cfg = {"google_accounts": [], "google_user_email": "old@example.test"}
    assert ga.configured_accounts(cfg) == []


def test_signed_in_accounts_reads_credentials_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_MCP_CREDENTIALS_DIR", str(tmp_path))
    (tmp_path / "One@Example.test.json").write_text("{}")
    (tmp_path / "two@example.test.json").write_text("{}")
    (tmp_path / "notes.txt").write_text("x")
    assert ga.signed_in_accounts() == ["one@example.test", "two@example.test"]


def test_signed_in_accounts_missing_dir_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_MCP_CREDENTIALS_DIR", str(tmp_path / "absent"))
    assert ga.signed_in_accounts() == []


def test_resolve_keeps_listed_account():
    assert ga.resolve_google_account("B@example.test", ["a@example.test", "b@example.test"], []) == "b@example.test"


def test_resolve_rewrites_unlisted_or_missing_to_default():
    accounts = ["a@example.test", "b@example.test"]
    assert ga.resolve_google_account("other@example.test", accounts, []) == "a@example.test"
    assert ga.resolve_google_account(None, accounts, []) == "a@example.test"
    assert ga.resolve_google_account("", accounts, []) == "a@example.test"


def test_resolve_with_no_accounts_uses_sole_signed_in_file():
    assert ga.resolve_google_account("x@example.test", [], ["only@example.test"]) == "only@example.test"


def test_resolve_with_no_accounts_and_no_unique_file_raises():
    with pytest.raises(ga.GoogleAccountError) as exc:
        ga.resolve_google_account(None, [], [])
    assert "Settings" in str(exc.value)
    with pytest.raises(ga.GoogleAccountError):
        ga.resolve_google_account(None, [], ["a@example.test", "b@example.test"])


def test_resolve_for_call_loads_config(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_MCP_CREDENTIALS_DIR", str(tmp_path))
    monkeypatch.setattr("config.load_config", lambda: {"google_accounts": ["a@example.test"]})
    assert ga.resolve_google_account_for_call("zzz@example.test") == "a@example.test"


def test_probe_invalid_client(monkeypatch):
    monkeypatch.setattr(ga, "_post_token", lambda data, timeout: (401, {"error": "invalid_client"}))
    assert ga.probe_google_client("id.apps.googleusercontent.com", "aigator-fake-api-key") == "invalid_client"


def test_probe_invalid_grant_means_credentials_are_valid(monkeypatch):
    monkeypatch.setattr(ga, "_post_token", lambda data, timeout: (400, {"error": "invalid_grant"}))
    assert ga.probe_google_client("id.apps.googleusercontent.com", "aigator-fake-api-key") == "ok"


def test_probe_network_failure_is_unknown(monkeypatch):
    def boom(data, timeout):
        raise OSError("offline")

    monkeypatch.setattr(ga, "_post_token", boom)
    assert ga.probe_google_client("id.apps.googleusercontent.com", "aigator-fake-api-key") == "unknown"
