# Listing recordings is Skype-only; share links are resolved per row, on demand.
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import importlib.util

import pytest

_SCRIPT = (
    pathlib.Path(__file__).parent.parent
    / "web"
    / "skills"
    / "m365-teams"
    / "scripts"
    / "transcript_recording.py"
)
spec = importlib.util.spec_from_file_location("_tx_recording_under_test", str(_SCRIPT))
rec = importlib.util.module_from_spec(spec)
sys.modules["_tx_recording_under_test"] = rec
spec.loader.exec_module(rec)

SHARE = "https://amd.sharepoint.com/:v:/s/x/abc"


class _GraphError(Exception):
    def __init__(self, status_code):
        super().__init__(f"graph {status_code}")
        self.status_code = status_code


@pytest.fixture(autouse=True)
def _clear_cache():
    rec._SHARE_CACHE.clear()
    yield
    rec._SHARE_CACHE.clear()


def test_list_recordings_never_resolves_share_links(monkeypatch):
    monkeypatch.setattr(
        rec,
        "_scan_chat_for_recordings",
        lambda chat_id: [(SHARE, "Weekly", "Weekly.mp4", True, "2026-10-26T15:00:00Z")],
    )

    def _boom(url):
        raise AssertionError("must not call Graph while listing")

    monkeypatch.setattr(rec, "_resolve_share_to_drive_item", _boom)
    out = rec.list_recordings_from_chat("19:meeting_x@thread.v2")
    assert len(out) == 1
    assert out[0].drive_id == "" and out[0].item_id == ""
    assert out[0].share_url == SHARE and out[0].web_url == SHARE
    assert out[0].has_transcript is True
    assert out[0].created_at == "2026-10-26T15:00:00Z"


def test_list_recordings_empty_chat(monkeypatch):
    monkeypatch.setattr(rec, "_scan_chat_for_recordings", lambda chat_id: [])
    assert rec.list_recordings_from_chat("c") == []


def test_resolve_share_success_is_cached(monkeypatch):
    calls = []

    def _ok(url):
        calls.append(url)
        return "b!drive", "01ITEM", "https://amd.sharepoint.com/web"

    monkeypatch.setattr(rec, "_resolve_share_to_drive_item", _ok)
    first = rec.resolve_share(SHARE)
    second = rec.resolve_share(SHARE)
    assert first == {
        "drive_id": "b!drive",
        "item_id": "01ITEM",
        "web_url": "https://amd.sharepoint.com/web",
        "error": None,
    }
    assert second == first
    assert calls == [SHARE]


@pytest.mark.parametrize(
    "status,expected",
    [(404, "expired"), (410, "expired"), (401, "auth"), (403, "auth"), (500, "failed")],
)
def test_resolve_share_maps_status_to_error(monkeypatch, status, expected):
    def _fail(url):
        raise _GraphError(status)

    monkeypatch.setattr(rec, "_resolve_share_to_drive_item", _fail)
    out = rec.resolve_share(SHARE)
    assert out["error"] == expected
    assert out["drive_id"] == "" and out["item_id"] == ""
    assert out["web_url"] == SHARE


def test_resolve_share_without_status_is_failed(monkeypatch):
    def _fail(url):
        raise RuntimeError("network down")

    monkeypatch.setattr(rec, "_resolve_share_to_drive_item", _fail)
    assert rec.resolve_share(SHARE)["error"] == "failed"


def test_resolve_share_failure_is_not_cached(monkeypatch):
    seq = iter([_GraphError(403), ("b!d", "01I", "w")])

    def _next(url):
        v = next(seq)
        if isinstance(v, Exception):
            raise v
        return v

    monkeypatch.setattr(rec, "_resolve_share_to_drive_item", _next)
    assert rec.resolve_share(SHARE)["error"] == "auth"
    assert rec.resolve_share(SHARE)["error"] is None


def test_resolve_recordings_from_chat_still_resolves_inline(monkeypatch):
    monkeypatch.setattr(
        rec,
        "_scan_chat_for_recordings",
        lambda chat_id: [(SHARE, "T", "n.mp4", True, "2026-10-26T15:00:00Z")],
    )
    monkeypatch.setattr(
        rec, "_resolve_share_to_drive_item", lambda u: ("b!d", "01I", "https://w")
    )
    out = rec.resolve_recordings_from_chat("c")
    assert out[0].drive_id == "b!d" and out[0].item_id == "01I"
