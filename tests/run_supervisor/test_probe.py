import http.server
import pathlib
import socket
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "web"))

import pytest

from runs import probe as probe_mod
from runs.probe import ProbeRefused, probe


class _Handler(http.server.BaseHTTPRequestHandler):
    seen_headers: list = []

    def do_GET(self):
        _Handler.seen_headers.append(dict(self.headers))
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/elsewhere")
            self.end_headers()
            return
        body = b"x" * 40_000 if self.path == "/big" else b"hello from the viewer"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.send_response(500)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _Handler.seen_headers = []
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_a_printed_loopback_address_is_fetched_with_get(server):
    out = probe(server + "/", [server + "/"], blocked_ports=set())
    assert out["reached"] and out["status"] == 200
    assert out["body"] == "hello from the viewer"


def test_a_path_under_a_printed_address_is_allowed(server):
    assert probe(server + "/api/health", [server + "/"], blocked_ports=set())["status"] == 200


def test_no_cookie_or_credential_is_sent(server):
    probe(server + "/", [server + "/"], blocked_ports=set())
    sent = {k.lower() for k in _Handler.seen_headers[0]}
    assert not sent & {"cookie", "authorization", "x-csrf-token"}


def test_a_redirect_is_returned_as_a_fact_and_not_followed(server):
    out = probe(server + "/redirect", [server + "/"], blocked_ports=set())
    assert out["status"] == 302
    assert out["redirect_to"] == "http://127.0.0.1:1/elsewhere"
    assert len(_Handler.seen_headers) == 1


def test_the_body_is_capped(server):
    out = probe(server + "/big", [server + "/"], blocked_ports=set())
    assert out["body_truncated"] is True
    assert len(out["body"]) == probe_mod.BODY_CAP_BYTES


def test_a_closed_port_is_reported_not_raised():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    url = f"http://127.0.0.1:{port}/"
    out = probe(url, [url], blocked_ports=set())
    assert out["reached"] is False and out["error"]


@pytest.mark.parametrize("url, why", [
    ("https://127.0.0.1:4173/", "Only http"),
    ("ftp://127.0.0.1:4173/", "Only http"),
    ("http://user:pw@127.0.0.1:4173/", "user name"),
    ("http://example.com:4173/", "127.0.0.1"),
    ("http://192.168.1.5:4173/", "127.0.0.1"),
    ("http://127.0.0.1.example.com:4173/", "127.0.0.1"),
    ("http://127.0.0.1:2375/", "container control"),
    ("http://127.0.0.1:2376/", "container control"),
    ("http://127.0.0.1:99999/", "valid URL"),
])
def test_unsafe_addresses_are_refused_even_if_a_run_printed_them(url, why):
    with pytest.raises(ProbeRefused, match=why):
        probe(url, [url], blocked_ports=set())


def test_the_backend_own_ports_are_refused():
    url = "http://127.0.0.1:8000/api/config"
    with pytest.raises(ProbeRefused, match="AI Gator"):
        probe(url, [url], blocked_ports={8000})


def test_the_live_backend_ports_include_a_socket_this_process_listens_on():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        assert s.getsockname()[1] in probe_mod.backend_ports()


def test_an_address_the_run_never_printed_is_refused(server):
    with pytest.raises(ProbeRefused, match="not printed by this run"):
        probe(server + "/", ["http://127.0.0.1:1/"], blocked_ports=set())


def test_a_name_that_resolves_off_loopback_is_refused(monkeypatch):
    monkeypatch.setattr(probe_mod.socket, "getaddrinfo",
                        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", 4173))])
    url = "http://localhost:4173/"
    with pytest.raises(ProbeRefused, match="loopback"):
        probe(url, [url], blocked_ports=set())
