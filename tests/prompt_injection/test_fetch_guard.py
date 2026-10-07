import urllib.error
import urllib.request

import pytest

from skills._always_on import tools


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/",
    "http://localhost:8000/api/csrf",
    "http://10.1.2.3/x",
    "http://192.168.0.5/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",
])
def test_private_loopback_and_metadata_addresses_are_refused(url):
    res = tools._tool_fetch_webpage(url)
    assert res["error"].startswith("Blocked:"), res


def test_a_hostname_that_resolves_to_a_private_address_is_refused(monkeypatch):
    monkeypatch.setattr(tools.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.0.0.7", 0))])
    assert tools._check_fetch_target("https://intranet.example.com/")["error"].startswith("Blocked:")


def test_a_public_address_is_allowed(monkeypatch):
    monkeypatch.setattr(tools.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])
    assert tools._check_fetch_target("https://example.com/page?q=1") is None


def test_an_unresolvable_host_is_left_to_fail_normally(monkeypatch):
    def boom(*a, **k):
        raise tools.socket.gaierror("no such host")
    monkeypatch.setattr(tools.socket, "getaddrinfo", boom)
    assert tools._check_fetch_target("https://nope.invalid/") is None


def test_a_long_query_string_is_refused(monkeypatch):
    monkeypatch.setattr(tools.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])
    res = tools._check_fetch_target("https://example.com/p?d=" + "a" * 301)
    assert res["error"].startswith("Blocked:") and "300" in res["error"]
    assert tools._check_fetch_target("https://example.com/p?d=" + "a" * 290) is None


def test_a_redirect_to_a_private_address_is_refused():
    req = urllib.request.Request("https://example.com/")
    with pytest.raises(urllib.error.URLError):
        tools._GuardedRedirect().redirect_request(req, None, 302, "Found", {}, "http://127.0.0.1:8000/x")


def test_a_long_path_is_refused_too(monkeypatch):
    monkeypatch.setattr(tools.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])
    res = tools._check_fetch_target("https://example.com/" + "a" * 301)
    assert res["error"].startswith("Blocked:") and "300" in res["error"] and "path and query" in res["error"]
    assert tools._check_fetch_target("https://example.com/" + "a" * 290) is None


def test_path_and_query_are_counted_together(monkeypatch):
    monkeypatch.setattr(tools.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])
    res = tools._check_fetch_target("https://example.com/" + "a" * 200 + "?d=" + "b" * 200)
    assert res["error"].startswith("Blocked:") and "300" in res["error"]
