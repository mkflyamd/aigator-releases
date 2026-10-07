import urllib.error
import urllib.request

import pytest

from skills._always_on import tools


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/",
    "http://localhost:8000/api/csrf",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",
])
def test_loopback_and_metadata_addresses_are_refused(url):
    res = tools._tool_fetch_webpage(url)
    assert res["error"].startswith("Blocked:"), res


@pytest.mark.parametrize("url", ["http://10.1.2.3/x", "http://192.168.0.5/", "http://172.16.4.4/"])
def test_internal_lan_addresses_are_allowed(url):
    assert tools._check_fetch_target(url) is None


def test_a_hostname_that_resolves_to_a_lan_address_is_allowed(monkeypatch):
    monkeypatch.setattr(tools.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.0.0.7", 0))])
    assert tools._check_fetch_target("https://intranet.example.com/") is None


def test_a_hostname_that_resolves_to_loopback_is_refused(monkeypatch):
    monkeypatch.setattr(tools.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 0))])
    assert tools._check_fetch_target("https://sneaky.example.com/")["error"].startswith("Blocked:")


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


def test_a_redirect_to_this_machine_is_refused():
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


def test_long_params_after_a_semicolon_are_counted(monkeypatch):
    monkeypatch.setattr(tools.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])
    res = tools._check_fetch_target("https://example.com/x;" + "A" * 2000)
    assert res["error"].startswith("Blocked:") and "300" in res["error"] and "path and query" in res["error"]
    assert tools._check_fetch_target("https://example.com/x;" + "A" * 200 + "?d=" + "b" * 200) is not None
    assert tools._check_fetch_target("https://example.com/x;" + "A" * 280) is None


def test_a_long_fragment_is_ignored_because_it_is_not_sent(monkeypatch):
    monkeypatch.setattr(tools.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])
    assert tools._check_fetch_target("https://example.com/p#" + "a" * 2000) is None


def test_a_redirect_with_long_params_is_refused(monkeypatch):
    monkeypatch.setattr(tools.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])
    req = urllib.request.Request("https://example.com/")
    with pytest.raises(urllib.error.URLError):
        tools._GuardedRedirect().redirect_request(req, None, 302, "Found", {}, "https://other.example.org/x;" + "A" * 2000)


def _public(monkeypatch):
    monkeypatch.setattr(tools.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])


def test_a_second_hash_cannot_hide_a_long_path(monkeypatch):
    # urllib drops only the text after the LAST "#", so the first "#" does not hide anything.
    _public(monkeypatch)
    url = "https://example.com/p#" + "A" * 2000 + "#b"
    assert urllib.request.Request(url).selector.startswith("/p#AAAA")
    res = tools._check_fetch_target(url)
    assert res["error"].startswith("Blocked:") and "300" in res["error"] and "path and query" in res["error"]


def test_a_single_long_fragment_is_allowed_because_urllib_does_not_send_it(monkeypatch):
    _public(monkeypatch)
    assert tools._check_fetch_target("https://example.com/p#" + "A" * 2000) is None


def test_the_cap_is_on_the_request_target_exactly(monkeypatch):
    _public(monkeypatch)
    assert tools._check_fetch_target("https://example.com/" + "a" * 299) is None  # request target is 300
    assert tools._check_fetch_target("https://example.com/" + "a" * 300)["error"].startswith("Blocked:")  # 301


def test_a_redirect_with_a_double_hash_target_is_refused(monkeypatch):
    _public(monkeypatch)
    req = urllib.request.Request("https://example.com/")
    with pytest.raises(urllib.error.URLError):
        tools._GuardedRedirect().redirect_request(
            req, None, 302, "Found", {}, "https://other.example.org/p#" + "A" * 2000 + "#b")


def test_a_malformed_url_is_blocked_not_raised():
    res = tools._check_fetch_target("not a url")
    assert res["error"].startswith("Blocked:")
