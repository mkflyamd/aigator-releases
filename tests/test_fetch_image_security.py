"""Security regression coverage for authenticated image downloads."""

import http.server
import socket
import threading
from pathlib import Path
from unittest.mock import patch

import httpcore
import httpx
import pytest

from skills.fetch_image.tools import (
    _PinnedBackend,
    _PinnedTransport,
    _safe_http_get,
    _save_image,
    _tool_fetch_image,
    _validate_fetch_url,
)


def test_source_flag_cannot_force_graph_auth_for_an_untrusted_url():
    with (
        patch("skills.fetch_image.tools._fetch_graph_image") as graph,
        patch("skills.fetch_image.tools._fetch_unauthenticated", return_value=(b"data", "image/png")) as anonymous,
        patch("skills.fetch_image.tools._save_image", return_value="/tmp/image.png"),
    ):
        result = _tool_fetch_image(url="https://example.com/image.png", source="graph")

    assert result["file_path"] == "/tmp/image.png"
    graph.assert_not_called()
    anonymous.assert_called_once_with("https://example.com/image.png")


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/image.png",
        "file:///etc/passwd",
        "https://127.0.0.1/image.png",
        "https://[::1]/image.png",
    ],
)
def test_validate_fetch_url_rejects_non_public_or_non_https_targets(url):
    with pytest.raises(ValueError):
        _validate_fetch_url(url)


def test_redirect_is_revalidated_pinned_and_credentials_are_not_forwarded():
    validated = []
    pinned = []
    requests = []
    resolved = {
        "https://graph.microsoft.com/v1.0/image": ["20.1.1.1"],
        "https://cdn.example.net/image.png": ["93.184.216.34"],
    }

    def validate(url, hosts=None):
        validated.append((url, hosts))
        return resolved[url]

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(302, headers={"location": "https://cdn.example.net/image.png"})
        return httpx.Response(200, content=b"image", headers={"content-type": "image/png"})

    def make_transport(addresses):
        pinned.append(addresses)
        return httpx.MockTransport(handler)

    with (
        patch("skills.fetch_image.tools._validate_fetch_url", side_effect=validate),
        patch("skills.fetch_image.tools._PinnedTransport", side_effect=make_transport),
    ):
        data, content_type = _safe_http_get(
            "https://graph.microsoft.com/v1.0/image",
            headers={"Authorization": "Bearer secret"},
            allowed_hosts={"graph.microsoft.com"},
        )

    assert data == b"image"
    assert content_type == "image/png"
    assert validated == [
        ("https://graph.microsoft.com/v1.0/image", {"graph.microsoft.com"}),
        ("https://cdn.example.net/image.png", None),
    ]
    assert pinned == [["20.1.1.1"], ["93.184.216.34"]]
    assert requests[0].headers["authorization"] == "Bearer secret"
    assert "authorization" not in requests[1].headers


def test_validate_fetch_url_returns_the_validated_addresses():
    answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
    with patch("skills.fetch_image.tools.socket.getaddrinfo", return_value=answers):
        assert _validate_fetch_url("https://example.com/image.png") == ["93.184.216.34"]


def test_validate_fetch_url_rejects_a_mixed_public_and_private_answer():
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443)),
    ]
    with patch("skills.fetch_image.tools.socket.getaddrinfo", return_value=answers):
        with pytest.raises(ValueError):
            _validate_fetch_url("https://example.com/image.png")


def test_dns_rebinding_cannot_redirect_the_connection():
    """The connection must use the validated IP; the hostname is never resolved again."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            return None

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with httpx.Client(transport=_PinnedTransport(["127.0.0.1"]), trust_env=False) as client:
            response = client.get(f"http://rebind.invalid:{port}/")
        assert response.content == b"ok"
    finally:
        server.shutdown()
        server.server_close()


def test_pinned_backend_tries_next_address_after_a_connect_failure():
    backend = _PinnedBackend(["198.51.100.1", "93.184.216.34"])
    attempts = []

    def fake_connect(self, host, port, **kwargs):
        attempts.append(host)
        if host == "198.51.100.1":
            raise httpcore.ConnectError("unreachable")
        return "stream"

    with patch.object(httpcore.SyncBackend, "connect_tcp", fake_connect):
        assert backend.connect_tcp("example.com", 443) == "stream"

    assert attempts == ["198.51.100.1", "93.184.216.34"]


@pytest.mark.parametrize("hint", ["../../outside.png", r"..\\..\\outside.png", r"C:\\temp\\outside.png"])
def test_save_image_sanitizes_untrusted_filename_and_stays_in_output_root(tmp_path, monkeypatch, hint):
    monkeypatch.setattr("config.OUTPUTS_DIR", tmp_path)

    saved = _save_image(b"image-data", "image/png", hint)

    saved_path = Path(saved)
    assert saved_path.read_bytes() == b"image-data"
    assert saved_path.suffix == ".png"
    assert saved_path.is_relative_to(tmp_path / "fetch_image")
    assert saved_path.name == "outside.png"
