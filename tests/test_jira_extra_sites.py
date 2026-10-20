"""Additional Jira Cloud sites that share the primary email + API token."""

import base64
import json

import pytest

from skills._drafts import get_draft
from skills.jira import api, tools
from skills.jira.mutations import (
    JiraTargetResolutionError,
    available_targets,
    configured_extra_urls,
    validate_extra_site_url,
)

PRIMARY = "https://ci-default.atlassian.net"
EXTRA = "https://extra.atlassian.net"


@pytest.fixture(autouse=True)
def _cloud_env(monkeypatch):
    monkeypatch.setenv("JIRA_BASE_URL", PRIMARY)
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "aigator-fake-api-key")
    monkeypatch.delenv("JIRA_PAT_TOKEN", raising=False)


def _with_extras(monkeypatch, urls):
    monkeypatch.setattr("skills.jira.mutations.load_config", lambda: {"jira_extra_base_urls": urls})


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.content = json.dumps(payload).encode()
        self.text = json.dumps(payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("err", request=None, response=self)

    def json(self):
        return self._payload


class _FakePool:
    """Answers 200 only for hosts in `has_issue`; records every request."""

    def __init__(self, has_issue):
        self.has_issue = has_issue
        self.calls = []

    def request(self, method, url, headers=None, content=None):
        self.calls.append((method, url, headers))
        host = url.split("/rest/")[0]
        if host in self.has_issue:
            return _Resp(200, {"key": "GPUAI-1459", "id": "1", "fields": {}})
        return _Resp(404, {"errorMessages": ["Issue does not exist"]})


@pytest.mark.parametrize("url", [
    "https://x.atlassian.net", "https://x.atlassian.net/", "https://X.Atlassian.NET",
])
def test_validate_accepts_cloud_site_root(url):
    assert validate_extra_site_url(url) == "https://x.atlassian.net"


@pytest.mark.parametrize("url", [
    "http://x.atlassian.net",
    "https://evil.example.com",
    "https://x.atlassian.net.evil.com",
    "https://x.atlassian.net@evil.com",
    "https://x.atlassian.net:8443",
    "https://x.atlassian.net/jira",
    "https://x.atlassian.net/browse/ABC-1",
    "https://atlassian.net",
    "",
])
def test_validate_rejects_other_hosts_and_shapes(url):
    with pytest.raises(JiraTargetResolutionError):
        validate_extra_site_url(url)


def test_configured_extra_urls_drops_invalid_duplicate_and_primary(monkeypatch):
    _with_extras(monkeypatch, [EXTRA, EXTRA + "/", "https://evil.example.com", PRIMARY, 5])
    assert configured_extra_urls() == [EXTRA]


def test_extras_become_builtin_targets_after_the_primary(monkeypatch):
    _with_extras(monkeypatch, [EXTRA])
    targets = available_targets()
    assert [t.base_url for t in targets] == [PRIMARY, EXTRA]
    assert all(t.adapter == "builtin-rest" for t in targets)


def test_extras_ignored_when_primary_is_not_cloud(monkeypatch):
    _with_extras(monkeypatch, [EXTRA])
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: False)
    assert [t.base_url for t in available_targets()] == [PRIMARY]


def test_jira_api_uses_extra_host_with_the_primary_credentials(monkeypatch):
    _with_extras(monkeypatch, [EXTRA])
    pool = _FakePool({EXTRA})
    monkeypatch.setattr(api, "_get_pool", lambda: pool)
    with api.use_site(EXTRA):
        api.jira_api("GET", "issue/GPUAI-1459")
    method, url, headers = pool.calls[0]
    assert url == f"{EXTRA}/rest/api/3/issue/GPUAI-1459"
    expected = "Basic " + base64.b64encode(b"user@example.com:aigator-fake-api-key").decode()
    assert headers["Authorization"] == expected


def test_jira_api_refuses_host_that_is_not_a_configured_extra(monkeypatch):
    _with_extras(monkeypatch, [EXTRA])
    pool = _FakePool({"https://evil.example.com"})
    monkeypatch.setattr(api, "_get_pool", lambda: pool)
    with api.use_site("https://evil.example.com"):
        with pytest.raises(RuntimeError, match="not configured to share"):
            api.jira_api("GET", "issue/GPUAI-1459")
    assert pool.calls == []


def test_jira_api_refuses_override_for_a_pat_primary(monkeypatch):
    _with_extras(monkeypatch, [EXTRA])
    monkeypatch.setenv("JIRA_PAT_TOKEN", "aigator-fake-api-key")
    pool = _FakePool({EXTRA})
    monkeypatch.setattr(api, "_get_pool", lambda: pool)
    with api.use_site(EXTRA):
        with pytest.raises(RuntimeError, match="not configured to share"):
            api.jira_api("GET", "issue/GPUAI-1459")
    assert pool.calls == []


def test_for_target_routes_to_extra_and_rejects_unknown_site(monkeypatch):
    _with_extras(monkeypatch, [EXTRA])
    pool = _FakePool({EXTRA})
    monkeypatch.setattr(api, "_get_pool", lambda: pool)
    extra = next(t for t in available_targets() if t.base_url == EXTRA)
    api.jira_api_for_target(extra, "GET", "issue/GPUAI-1459")
    assert pool.calls[0][1].startswith(EXTRA)

    from dataclasses import replace
    stranger = replace(extra, base_url="https://stranger.atlassian.net")
    with pytest.raises(RuntimeError, match="changed after this draft"):
        api.jira_api_for_target(stranger, "GET", "issue/GPUAI-1459")


def test_bare_key_comment_draft_targets_the_site_that_has_the_issue(monkeypatch):
    """The original 404: the key lives only on the extra site."""
    _with_extras(monkeypatch, [EXTRA])
    pool = _FakePool({EXTRA})
    monkeypatch.setattr(api, "_get_pool", lambda: pool)
    result = tools._tool_jira_add_comment("GPUAI-1459", "Thanks for the updates!", "ctx-extra-1")
    assert "error" not in result, result
    assert get_draft(result["data"]["draft_id"]) is not None
    assert result["data"]["jira_site"]["base_url"] == EXTRA
    assert any(url.startswith(EXTRA) for _, url, _ in pool.calls)


def test_get_issue_reports_the_extra_sites_browse_url(monkeypatch):
    _with_extras(monkeypatch, [EXTRA])
    pool = _FakePool({EXTRA})
    monkeypatch.setattr(api, "_get_pool", lambda: pool)
    result = tools._tool_jira_get_issue("GPUAI-1459", "ctx-extra-2")
    assert result["url"] == f"{EXTRA}/browse/GPUAI-1459"


# ── create form: site chosen by project key (no issue key exists yet) ────────

def _two_targets():
    from skills.jira import mutations
    primary = mutations.JiraTarget(
        id="builtin:https://primary.atlassian.net", base_url="https://primary.atlassian.net",
        adapter="builtin-rest", is_cloud=True,
    )
    extra = mutations.JiraTarget(
        id="builtin:https://extra.atlassian.net", base_url="https://extra.atlassian.net",
        adapter="builtin-rest", is_cloud=True,
    )
    return primary, extra


def _projects_on(monkeypatch, hosts):
    from skills.jira import mutations

    def fake_api(target, method, path, body=None):
        if path.startswith("project/") and target.base_url in hosts:
            return {"key": path.split("/", 1)[1]}
        raise RuntimeError("HTTP 404")

    primary, extra = _two_targets()
    monkeypatch.setattr(mutations, "available_targets", lambda: [primary, extra])
    monkeypatch.setattr(mutations, "selected_target_for_context", lambda ctx: None)
    monkeypatch.setattr(mutations.api, "jira_api_for_target", fake_api)
    mutations._probe_cache.clear()
    return primary, extra


def test_project_resolves_to_the_only_site_that_has_it(monkeypatch):
    from skills.jira import mutations
    _, extra = _projects_on(monkeypatch, {"https://extra.atlassian.net"})
    assert mutations.resolve_target_for_project("arq", "ctx").id == extra.id


def test_project_on_several_sites_is_ambiguous(monkeypatch):
    from skills.jira import mutations
    _projects_on(monkeypatch, {"https://primary.atlassian.net", "https://extra.atlassian.net"})
    with pytest.raises(mutations.JiraTargetResolutionError, match="ambiguous"):
        mutations.resolve_target_for_project("ARQ", "ctx")


def test_unknown_project_names_the_project_not_an_empty_issue(monkeypatch):
    from skills.jira import mutations
    _projects_on(monkeypatch, set())
    with pytest.raises(mutations.JiraTargetResolutionError, match="Project 'ARQ' was not found"):
        mutations.resolve_target_for_project("ARQ", "ctx")
