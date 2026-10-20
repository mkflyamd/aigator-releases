"""Additional Confluence Cloud sites that share the primary email + API token."""

import base64
import json

import pytest

from skills.confluence import api, tools

PRIMARY = "https://primary.atlassian.net/wiki"
EXTRA = "https://extra.atlassian.net/wiki"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_BASE_URL", PRIMARY)
    monkeypatch.setenv("CONFLUENCE_EMAIL", "user@example.com")
    monkeypatch.setenv("CONFLUENCE_PAT", "aigator-fake-api-key")


def _with_extras(monkeypatch, urls):
    monkeypatch.setattr("config.load_config", lambda: {"confluence_extra_base_urls": urls})


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.content = json.dumps(payload).encode()
        self.text = json.dumps(payload)
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("err", request=None, response=self)

    def json(self):
        return self._payload


class _FakePool:
    """Pages exist only on hosts in `pages`; records every request."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def request(self, method, url, headers=None, content=None):
        self.calls.append((method, url, headers))
        site = url.split("/rest/")[0]
        if site not in self.pages:
            return _Resp(404, {"message": "No content found"})
        if "content/search" in url:
            return _Resp(200, {"results": [{"id": "7", "title": f"hit on {site}", "_links": {"webui": "/x"}}]})
        return _Resp(200, {"id": "123", "title": "T", "version": {"number": 1}, "_links": {"webui": "/spaces/S/pages/123"}})


@pytest.mark.parametrize("url,expected", [
    ("https://x.atlassian.net", "https://x.atlassian.net/wiki"),
    ("https://X.Atlassian.NET/wiki/", "https://x.atlassian.net/wiki"),
])
def test_validate_accepts_cloud_sites(url, expected):
    assert api.validate_extra_site_url(url) == expected


@pytest.mark.parametrize("url", [
    "http://x.atlassian.net/wiki",
    "https://evil.example.com/wiki",
    "https://x.atlassian.net.evil.com/wiki",
    "https://x.atlassian.net@evil.com/wiki",
    "https://x.atlassian.net:8443/wiki",
    "https://x.atlassian.net/wiki/spaces/A",
    "https://atlassian.net/wiki",
    "",
])
def test_validate_rejects_other_hosts_and_shapes(url):
    with pytest.raises(ValueError):
        api.validate_extra_site_url(url)


def test_configured_sites_lists_primary_then_valid_extras(monkeypatch):
    _with_extras(monkeypatch, [EXTRA, EXTRA, "https://evil.example.com/wiki", PRIMARY, 5])
    assert api.configured_sites() == [PRIMARY, EXTRA]


def test_extras_ignored_when_primary_is_not_cloud(monkeypatch):
    _with_extras(monkeypatch, [EXTRA])
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://wiki.corp.example.com")
    assert api.configured_sites() == ["https://wiki.corp.example.com"]


def test_api_uses_extra_host_with_the_primary_credentials(monkeypatch):
    _with_extras(monkeypatch, [EXTRA])
    pool = _FakePool({EXTRA})
    monkeypatch.setattr(api, "_get_pool", lambda: pool)
    with api.use_site(EXTRA):
        api.confluence_api("GET", "content/123")
    _, url, headers = pool.calls[0]
    assert url == f"{EXTRA}/rest/api/content/123"
    expected = "Basic " + base64.b64encode(b"user@example.com:aigator-fake-api-key").decode()
    assert headers["Authorization"] == expected


def test_api_refuses_a_host_that_is_not_a_configured_extra(monkeypatch):
    _with_extras(monkeypatch, [EXTRA])
    pool = _FakePool({"https://evil.example.com/wiki"})
    monkeypatch.setattr(api, "_get_pool", lambda: pool)
    with api.use_site("https://evil.example.com/wiki"):
        with pytest.raises(RuntimeError, match="not configured to share"):
            api.confluence_api("GET", "content/123")
    assert pool.calls == []


def test_read_by_url_goes_to_that_sites_host(monkeypatch):
    _with_extras(monkeypatch, [EXTRA])
    pool = _FakePool({PRIMARY, EXTRA})
    monkeypatch.setattr(api, "_get_pool", lambda: pool)
    result = tools.TOOL_HANDLERS["read_confluence_page"](
        page_id="https://extra.atlassian.net/wiki/spaces/S/pages/123/Title"
    )
    assert "error" not in result, result
    assert result["url"].startswith(EXTRA)
    assert all(url.startswith(EXTRA) for _, url, _ in pool.calls)


def test_read_by_url_on_unconfigured_host_is_refused_without_a_request(monkeypatch):
    _with_extras(monkeypatch, [EXTRA])
    pool = _FakePool({PRIMARY, EXTRA})
    monkeypatch.setattr(api, "_get_pool", lambda: pool)
    result = tools.TOOL_HANDLERS["read_confluence_page"](
        page_id="https://evil.example.com/wiki/spaces/S/pages/123/Title"
    )
    assert "not on a configured Confluence site" in result["error"]
    assert pool.calls == []


def test_bare_id_is_found_on_the_site_that_has_it(monkeypatch):
    _with_extras(monkeypatch, [EXTRA])
    pool = _FakePool({EXTRA})
    monkeypatch.setattr(api, "_get_pool", lambda: pool)
    result = tools.TOOL_HANDLERS["read_confluence_page"](page_id="123")
    assert "error" not in result, result
    assert result["url"].startswith(EXTRA)


def test_write_refuses_an_id_present_on_two_sites(monkeypatch):
    _with_extras(monkeypatch, [EXTRA])
    pool = _FakePool({PRIMARY, EXTRA})
    monkeypatch.setattr(api, "_get_pool", lambda: pool)
    result = tools.TOOL_HANDLERS["update_confluence_page"](page_id="123", body="<p>x</p>")
    assert "more than one Confluence site" in result["error"]
    assert not any(m == "PUT" for m, _, _ in pool.calls)


def test_search_merges_results_from_every_site(monkeypatch):
    _with_extras(monkeypatch, [EXTRA])
    pool = _FakePool({PRIMARY, EXTRA})
    monkeypatch.setattr(api, "_get_pool", lambda: pool)
    result = tools.TOOL_HANDLERS["search_confluence"](query="runbook")
    assert {r["site"] for r in result["results"]} == {PRIMARY, EXTRA}


def test_create_targets_the_requested_site_and_rejects_unknown(monkeypatch):
    _with_extras(monkeypatch, [EXTRA])
    pool = _FakePool({PRIMARY, EXTRA})
    monkeypatch.setattr(api, "_get_pool", lambda: pool)
    ok = tools.TOOL_HANDLERS["create_confluence_page"](
        space_key="S", title="T", body="<p>x</p>", site="https://extra.atlassian.net/wiki"
    )
    assert ok["url"].startswith(EXTRA)
    bad = tools.TOOL_HANDLERS["create_confluence_page"](
        space_key="S", title="T", body="<p>x</p>", site="https://evil.example.com/wiki"
    )
    assert "not on a configured Confluence site" in bad["error"]


def test_single_site_behaviour_is_unchanged(monkeypatch):
    _with_extras(monkeypatch, [])
    pool = _FakePool({PRIMARY})
    monkeypatch.setattr(api, "_get_pool", lambda: pool)
    result = tools.TOOL_HANDLERS["read_confluence_page"](page_id="123")
    assert result["url"].startswith(PRIMARY)
    assert len(pool.calls) == 1
