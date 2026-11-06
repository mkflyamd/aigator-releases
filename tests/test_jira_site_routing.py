"""Jira calls must go to the site the user named or the site that hosts the project."""

import pytest
from skills.jira import tools
from skills.jira.mutations import (
    JiraTargetResolutionError,
    resolve_target_for_context,
    select_target_for_context,
)

PRIMARY = "https://site-a.atlassian.net"
OTHER = "https://site-b.atlassian.net"


@pytest.fixture(autouse=True)
def two_direct_sites(monkeypatch):
    monkeypatch.setenv("JIRA_BASE_URL", PRIMARY)
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: PRIMARY)
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: True)
    monkeypatch.setattr("mcp.manager._load_connections", list)
    monkeypatch.setattr(
        "skills.jira.mutations.load_config",
        lambda: {"jira_extra_base_urls": [OTHER]},
    )


def _select_primary(context_id):
    select_target_for_context(context_id, f"builtin:{PRIMARY}")


def test_read_url_for_another_site_beats_a_stale_tab_selection():
    _select_primary("tab-stale-read")

    target = resolve_target_for_context(f"{OTHER}/browse/ROCMAI-4", "tab-stale-read")

    assert target.base_url == OTHER


def test_write_url_for_another_site_still_fails_closed_against_tab_selection():
    _select_primary("tab-stale-write")

    with pytest.raises(JiraTargetResolutionError, match="does not belong to the selected Jira site"):
        resolve_target_for_context(
            f"{OTHER}/browse/ROCMAI-4", "tab-stale-write", for_write=True
        )


def test_get_issue_resolves_the_pasted_url_not_the_stripped_key(monkeypatch):
    _select_primary("tab-get-issue")
    seen = []

    def fake_japi(target, method, path, body=None):
        seen.append((target.base_url, path))
        return {"key": "ROCMAI-4", "fields": {}, "names": {}}

    monkeypatch.setattr(tools, "_japi", fake_japi)

    result = tools._tool_jira_get_issue(f"{OTHER}/browse/ROCMAI-4", "tab-get-issue")

    assert "error" not in result
    assert seen[0][0] == OTHER


@pytest.mark.parametrize("selected", [True, False])
def test_search_on_a_project_runs_on_the_site_that_hosts_it(monkeypatch, selected):
    if selected:
        _select_primary("tab-search")
    hosts = {OTHER}
    monkeypatch.setattr(
        "skills.jira.tools._probe_project",
        lambda key, target, context_id="": target.base_url in hosts,
    )
    ran_on = []

    class _Site:
        def __init__(self, target):
            ran_on.append(target.base_url)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(tools, "_site", _Site)
    monkeypatch.setattr(tools, "_jira_search_post", lambda *a, **k: {"total": 0, "issues": []})

    tools._tool_jira_search("project = ROCMAI ORDER BY updated DESC", 5, "tab-search")

    assert ran_on == [OTHER]


def test_search_without_a_project_keeps_the_primary_site(monkeypatch):
    ran_on = []

    class _Site:
        def __init__(self, target):
            ran_on.append(target.base_url)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(tools, "_site", _Site)
    monkeypatch.setattr(tools, "_jira_search_post", lambda *a, **k: {"total": 0, "issues": []})

    tools._tool_jira_search("assignee = currentUser()", 5, "tab-no-project")

    assert ran_on == [PRIMARY]


def _fake_search_site(monkeypatch):
    ran_on = []

    class _Site:
        def __init__(self, target):
            ran_on.append(target.base_url)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(tools, "_site", _Site)
    monkeypatch.setattr(tools, "_jira_search_post", lambda *a, **k: {"total": 0, "issues": []})
    return ran_on


def test_failed_project_probe_keeps_the_preferred_site_and_is_not_cached(monkeypatch):
    calls = {"primary_ok": False}

    def fake_japi(target, method, path, body=None):
        if target.base_url == PRIMARY and not calls["primary_ok"]:
            raise RuntimeError("timed out")
        return {"key": "PROBEFAIL"}

    monkeypatch.setattr("skills.jira.api.jira_api_for_target", fake_japi)
    ran_on = _fake_search_site(monkeypatch)

    tools._tool_jira_search("project = PROBEFAIL", 5, "tab-probe-fail")
    assert ran_on == [PRIMARY]

    calls["primary_ok"] = True
    ran_on.clear()
    tools._tool_jira_search("project = PROBEFAIL", 5, "tab-probe-fail")
    assert ran_on == [PRIMARY]


def test_project_absent_from_the_preferred_site_still_moves_to_the_site_hosting_it(monkeypatch):
    def fake_japi(target, method, path, body=None):
        if target.base_url == PRIMARY:
            raise RuntimeError("HTTP 404: no such project")
        return {"key": "ONLYOTHER"}

    monkeypatch.setattr("skills.jira.api.jira_api_for_target", fake_japi)
    ran_on = _fake_search_site(monkeypatch)

    tools._tool_jira_search("project = ONLYOTHER", 5, "tab-probe-404")

    assert ran_on == [OTHER]
