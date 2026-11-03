import time
from unittest.mock import MagicMock, patch

import httpx

from skills.onedrive import tools as od


class _Resp:
    def __init__(self, status=200, data=None, headers=None, text=""):
        self.status_code = status
        self._data = data if data is not None else {}
        self.headers = headers or {}
        self.content = b"x"
        self.text = text

    def json(self):
        return self._data


def _gc():
    gc = MagicMock()
    gc.get_token.return_value = "aigator-fake-api-key"
    return gc


def _copy(monkeypatch, poll):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(202, headers={"Location": "https://monitor.example/m1"}))
    monkeypatch.setattr(httpx, "get", poll)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    with patch("skills._m365.helpers.get_skill_client", return_value=_gc()):
        return od._tool_copy_onedrive_file("d1", "i1", "d2", "f2")


def test_copy_poll_sends_no_authorization(monkeypatch):
    seen = []

    def poll(url, **kw):
        seen.append(kw.get("headers"))
        return _Resp(200, {"status": "completed", "resourceId": "NEW1"})

    out = _copy(monkeypatch, poll)
    assert out["status"] == "completed" and out["item_id"] == "NEW1"
    assert not seen[0], "monitor URL is pre-authenticated; no headers may be sent"


def test_copy_poll_bare_item_json_counts_as_completed(monkeypatch):
    out = _copy(monkeypatch, lambda url, **kw: _Resp(200, {"id": "NEW2", "name": "a.docx", "parentReference": {"driveId": "d2"}}))
    assert out == {"status": "completed", "item_id": "NEW2", "dest_drive_id": "d2", "name": "a.docx"}


def test_copy_poll_errors_are_surfaced_not_swallowed(monkeypatch):
    def poll(url, **kw):
        raise RuntimeError("boom")

    out = _copy(monkeypatch, poll)
    assert out["status"] == "pending"
    assert out["poll_error"] == "boom"


def test_copy_failed_status_has_error_code(monkeypatch):
    out = _copy(monkeypatch, lambda url, **kw: _Resp(200, {"status": "failed", "error": {"message": "nope"}}))
    assert out["error"].startswith("Copy failed")
    assert out["error_code"] == "unknown"


def test_copy_request_http_error_has_error_code(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(404, text="not here"))
    with patch("skills._m365.helpers.get_skill_client", return_value=_gc()):
        out = od._tool_copy_onedrive_file("d1", "i1", "d2", "f2")
    assert out["error_code"] == "not_found"
    assert "404" in out["error"]


def test_move_locked_has_error_code_and_keeps_message():
    class Locked(Exception):
        status_code = 423

    gc = MagicMock()
    gc.patch.side_effect = Locked("Graph API 423: resourceLocked")
    with patch("skills._m365.helpers.get_skill_client", return_value=gc):
        out = od._tool_move_onedrive_file("d1", "i1", "d2", "f2")
    assert out["error"].startswith("Move failed:")
    assert out["error_code"] == "locked"


def test_get_item_error_has_error_code():
    class Missing(Exception):
        status_code = 404

    gc = MagicMock()
    gc.get.side_effect = Missing("Graph API 404")
    with patch("skills._m365.helpers.get_skill_client", return_value=gc):
        out = od._tool_get_onedrive_item("d1", "i1")
    assert out["error_code"] == "not_found"


def test_copy_without_monitor_url_has_error_code(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(202))
    with patch("skills._m365.helpers.get_skill_client", return_value=_gc()):
        out = od._tool_copy_onedrive_file("d1", "i1", "d2", "f2")
    assert "monitor URL" in out["error"]
    assert out["error_code"] == "unknown"
