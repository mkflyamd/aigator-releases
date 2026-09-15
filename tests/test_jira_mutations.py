"""Safety contract for Jira target resolution and verified mutation payloads."""

import pytest

from skills.jira.mutations import (
    JiraTargetResolutionError,
    compare_jira_fields,
    configured_builtin_target,
    resolve_builtin_target,
    target_from_draft,
    verified_result,
)


def test_full_url_on_another_site_fails_closed(monkeypatch):
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://amd-hub.atlassian.net")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: True)

    with pytest.raises(JiraTargetResolutionError, match="will not redirect"):
        resolve_builtin_target("https://amd.atlassian.net/browse/ICCM-17432")


def test_same_site_url_resolves_to_canonical_target(monkeypatch):
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://amd.atlassian.net/")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: True)

    target = resolve_builtin_target("https://amd.atlassian.net/browse/ICCM-17432")

    assert target.base_url == "https://amd.atlassian.net"
    assert target.issue_url("ICCM-17432") == "https://amd.atlassian.net/browse/ICCM-17432"


def test_same_site_url_with_configured_base_path_resolves(monkeypatch):
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://jira.example.com/jira")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: False)

    target = resolve_builtin_target("https://jira.example.com/jira/browse/PROJ-1")

    assert target.issue_url("PROJ-1") == "https://jira.example.com/jira/browse/PROJ-1"


def test_approval_rejects_draft_if_configured_site_changed(monkeypatch):
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://amd-hub.atlassian.net")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: True)
    draft_target = {
        "id": "builtin:https://amd.atlassian.net",
        "base_url": "https://amd.atlassian.net",
        "adapter": "builtin-rest",
        "is_cloud": True,
        "connection_id": "",
        "resource_id": "",
    }

    with pytest.raises(JiraTargetResolutionError, match="connection changed"):
        target_from_draft(draft_target)


def test_verified_result_preserves_requested_applied_and_verified_state(monkeypatch):
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://amd.atlassian.net")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: True)
    target = configured_builtin_target()

    result = verified_result(
        target,
        requested={"operation": "add_watcher", "account_id": "abc"},
        applied={"endpoint": "issue/ICCM-1/watchers"},
        verified={"watcher_account_ids": ["abc"]},
    )

    assert result["ok"] is True
    assert result["target"]["base_url"] == "https://amd.atlassian.net"
    assert result["verified"]["watcher_account_ids"] == ["abc"]


def test_compare_jira_fields_requires_every_requested_field():
    confirmed, rejected = compare_jira_fields(
        {
            "project": {"key": "ICCM"},
            "issuetype": {"name": "Business Requirement"},
            "priority": {"name": "High"},
            "customfield_123": {"id": "42"},
        },
        {
            "project": {"key": "ICCM", "name": "Jira Change Management"},
            "issuetype": {"name": "Business Requirement"},
            "priority": {"name": "Low"},
        },
    )

    assert set(confirmed) == {"project", "issuetype"}
    assert set(rejected) == {"priority", "customfield_123"}
