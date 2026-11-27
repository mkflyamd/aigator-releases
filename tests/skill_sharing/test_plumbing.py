from skills._files.errors import classify_status
from skills._m365 import file_transfer as ft
from skills._m365.helpers import GraphClient


class _FakeResponse:
    def __init__(self, content=b"", json_body=None):
        self.content = content
        self._json = json_body

    def json(self):
        return self._json


def _client(monkeypatch, calls, response):
    gc = object.__new__(GraphClient)
    monkeypatch.setattr(gc, "_headers", lambda: {"Authorization": "Bearer aigator-fake-api-key"}, raising=False)

    def fake_request(method, url, *, headers=None, content=None, label="", retry_unanswered=True):
        calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "content": content,
                "retry_unanswered": retry_unanswered,
            }
        )
        return response

    monkeypatch.setattr(gc, "_request", fake_request, raising=False)
    return gc


def test_412_is_a_conflict():
    assert classify_status(412) == "conflict"


def test_get_bytes_returns_raw_content(monkeypatch):
    calls = []
    gc = _client(monkeypatch, calls, _FakeResponse(content=b"PK\x03\x04data"))
    assert gc.get_bytes("/drives/d1/items/i1/content") == b"PK\x03\x04data"
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith("/drives/d1/items/i1/content")


def test_put_binary_merges_extra_headers(monkeypatch):
    calls = []
    gc = _client(monkeypatch, calls, _FakeResponse(content=b"", json_body=None))
    gc.put_binary("/drives/d/items/f:/skill.json:/content", b"{}", "application/json", extra_headers={"If-Match": '"e1"'})
    headers = calls[0]["headers"]
    assert headers["If-Match"] == '"e1"'
    assert headers["Content-Type"] == "application/json"
    assert headers["Authorization"] == "Bearer aigator-fake-api-key"
    assert calls[0]["retry_unanswered"] is False


def test_put_binary_without_extra_headers_is_unchanged(monkeypatch):
    calls = []
    gc = _client(monkeypatch, calls, _FakeResponse(content=b"", json_body=None))
    gc.put_binary("/drives/d/items/f:/a:/content", b"x")
    assert set(calls[0]["headers"]) == {"Authorization", "Content-Type"}


class _FakeGc:
    def __init__(self, error=None):
        self.error = error
        self.puts = []

    def put_binary(self, path, data, content_type="application/octet-stream", extra_headers=None):
        self.puts.append({"path": path, "data": data, "extra_headers": extra_headers})
        if self.error:
            raise self.error
        return {"id": "item1", "name": "skill.json", "webUrl": "https://x/skill.json", "size": len(data)}


class _Status(Exception):
    def __init__(self, status):
        super().__init__(f"http {status}")
        self.status_code = status


def test_replace_in_folder_uses_replace_conflict_behavior():
    gc = _FakeGc()
    out = ft.replace_in_folder(gc, ft.bytes_source("bundle.zip", b"abc"), "d1", "f1")
    assert out["status"] == "saved"
    assert out["id"] == "item1"
    assert "conflictBehavior=replace" in gc.puts[0]["path"]
    assert gc.puts[0]["extra_headers"] is None


def test_replace_in_folder_sends_if_match():
    gc = _FakeGc()
    ft.replace_in_folder(gc, ft.bytes_source("skill.json", b"{}"), "d1", "f1", if_match='"e1"')
    assert gc.puts[0]["extra_headers"] == {"If-Match": '"e1"'}


def test_replace_in_folder_412_is_a_conflict():
    gc = _FakeGc(error=_Status(412))
    out = ft.replace_in_folder(gc, ft.bytes_source("skill.json", b"{}"), "d1", "f1", if_match='"e1"')
    assert out["status"] == "error"
    assert out["error_code"] == "conflict"


def test_replace_in_folder_if_match_needs_a_small_file():
    gc = _FakeGc()
    big = ft.Source(name="big.bin", size=ft.SIMPLE_UPLOAD_MAX + 1, open=lambda: iter([]))
    out = ft.replace_in_folder(gc, big, "d1", "f1", if_match='"e1"')
    assert out["status"] == "error"
    assert out["error"] == "if_match_needs_small_file"
    assert gc.puts == []


def test_store_in_folder_still_renames_on_clash():
    gc = _FakeGc()
    ft.store_in_folder(gc, ft.bytes_source("a.txt", b"x"), "d1", "f1")
    assert "conflictBehavior=rename" in gc.puts[0]["path"]
    assert gc.puts[0]["extra_headers"] is None
