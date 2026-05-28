import json
from unittest.mock import MagicMock
from mcp.generic_client import GenericMCPClient

INIT_RESPONSE = json.dumps({
    "jsonrpc": "2.0", "id": 1,
    "result": {"serverInfo": {"name": "test", "version": "1"}, "capabilities": {}}
}).encode()


def _mock_response(body: bytes):
    resp = MagicMock()
    resp.read.return_value = body
    resp.headers.get = lambda k, d="": {"Content-Type": "application/json"}.get(k, d)
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_extra_headers_sent_in_request(monkeypatch):
    captured = {}

    def fake_open(req, timeout=None):
        captured["headers"] = dict(req.headers)
        return _mock_response(INIT_RESPONSE)

    monkeypatch.setattr("mcp.generic_client._OPENER.open", fake_open)
    GenericMCPClient({
        "url": "https://example.com/mcp",
        "auth_type": "none",
        "auth_value": "",
        "extra_headers": {"X-Postgres-Host": "db.example.com"},
    })
    assert captured["headers"].get("X-postgres-host") == "db.example.com"


def test_extra_headers_cannot_override_content_type(monkeypatch):
    captured = {}

    def fake_open(req, timeout=None):
        captured["headers"] = dict(req.headers)
        return _mock_response(INIT_RESPONSE)

    monkeypatch.setattr("mcp.generic_client._OPENER.open", fake_open)
    GenericMCPClient({
        "url": "https://example.com/mcp",
        "auth_type": "none",
        "auth_value": "",
        "extra_headers": {"Content-Type": "text/plain"},
    })
    assert captured["headers"].get("Content-type") == "application/json"


def test_extra_headers_cannot_override_accept(monkeypatch):
    captured = {}

    def fake_open(req, timeout=None):
        captured["headers"] = dict(req.headers)
        return _mock_response(INIT_RESPONSE)

    monkeypatch.setattr("mcp.generic_client._OPENER.open", fake_open)
    GenericMCPClient({
        "url": "https://example.com/mcp",
        "auth_type": "none",
        "auth_value": "",
        "extra_headers": {"Accept": "text/html"},
    })
    assert "application/json" in captured["headers"].get("Accept", "")


def test_no_extra_headers_still_works(monkeypatch):
    def fake_open(req, timeout=None):
        return _mock_response(INIT_RESPONSE)

    monkeypatch.setattr("mcp.generic_client._OPENER.open", fake_open)
    client = GenericMCPClient({
        "url": "https://example.com/mcp",
        "auth_type": "none",
        "auth_value": "",
    })
    assert client.server_info()["name"] == "test"
