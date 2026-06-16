from mcp.generic_client import GenericMCPClient


def _fake_connect(self):
    """Bypass network — just set the cached state _connect() would set."""
    self._server_info_cache = {"name": "test", "version": "1"}
    self._transport = "streamable_http"


def test_extra_headers_sent_in_request(monkeypatch):
    monkeypatch.setattr(GenericMCPClient, "_connect", _fake_connect)
    client = GenericMCPClient({
        "url": "https://example.com/mcp",
        "auth_type": "none",
        "auth_value": "",
        "extra_headers": {"X-Postgres-Host": "db.example.com"},
    })
    assert client._headers.get("X-Postgres-Host") == "db.example.com"


def test_extra_headers_cannot_override_content_type(monkeypatch):
    monkeypatch.setattr(GenericMCPClient, "_connect", _fake_connect)
    client = GenericMCPClient({
        "url": "https://example.com/mcp",
        "auth_type": "none",
        "auth_value": "",
        "extra_headers": {"Content-Type": "text/plain"},
    })
    assert client._headers.get("Content-Type") == "application/json"


def test_extra_headers_cannot_override_accept(monkeypatch):
    monkeypatch.setattr(GenericMCPClient, "_connect", _fake_connect)
    client = GenericMCPClient({
        "url": "https://example.com/mcp",
        "auth_type": "none",
        "auth_value": "",
        "extra_headers": {"Accept": "text/html"},
    })
    assert "application/json" in client._headers.get("Accept", "")


def test_no_extra_headers_still_works(monkeypatch):
    monkeypatch.setattr(GenericMCPClient, "_connect", _fake_connect)
    client = GenericMCPClient({
        "url": "https://example.com/mcp",
        "auth_type": "none",
        "auth_value": "",
    })
    assert client.server_info()["name"] == "test"
