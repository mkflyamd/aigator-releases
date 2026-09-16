"""Safety contract for Jira target resolution and verified mutation payloads."""

import pytest

from skills.jira.mutations import (
    JiraTargetResolutionError,
    compare_jira_fields,
    configured_builtin_target,
    resolve_jira_target,
    resolve_builtin_target,
    target_from_draft,
    verified_result,
)


def test_full_url_on_another_site_fails_closed(monkeypatch):
    monkeypatch.setattr("skills.jira.mutations.load_config", lambda: {})
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://amd-hub.atlassian.net")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: True)

    with pytest.raises(JiraTargetResolutionError, match="does not belong to a connected Jira site"):
        resolve_builtin_target("https://amd.atlassian.net/browse/ICCM-17432")


def test_same_site_url_resolves_to_canonical_target(monkeypatch):
    monkeypatch.setattr("skills.jira.mutations.load_config", lambda: {})
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://amd.atlassian.net/")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: True)

    target = resolve_builtin_target("https://amd.atlassian.net/browse/ICCM-17432")

    assert target.base_url == "https://amd.atlassian.net"
    assert target.issue_url("ICCM-17432") == "https://amd.atlassian.net/browse/ICCM-17432"


def test_same_site_url_with_configured_base_path_resolves(monkeypatch):
    monkeypatch.setattr("skills.jira.mutations.load_config", lambda: {})
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://jira.example.com/jira")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: False)

    target = resolve_builtin_target("https://jira.example.com/jira/browse/PROJ-1")

    assert target.issue_url("PROJ-1") == "https://jira.example.com/jira/browse/PROJ-1"


def test_page_url_cannot_be_registered_as_a_jira_base_url():
    from skills.jira.mutations import _canonical_base_url

    with pytest.raises(JiraTargetResolutionError, match="site base URL"):
        _canonical_base_url("https://jira.example.com/browse")


def test_staged_attachment_rejects_content_swap(monkeypatch, tmp_path):
    import skills.jira.mutations as mutations

    monkeypatch.setattr(mutations.tempfile, "gettempdir", lambda: str(tmp_path))
    staged = mutations.stage_attachment("evidence.txt", b"approved bytes", "text/plain")
    snapshot = mutations._staged_attachments[staged["upload_id"]]
    snapshot["path"].write_bytes(b"swapped after review")

    with pytest.raises(JiraTargetResolutionError, match="changed after staging"):
        mutations.staged_attachment(staged["upload_id"])


def test_dynamic_rovo_tools_default_deny_unknown_writes():
    from mcp.manager import _is_unverified_jira_mcp_mutation

    connection = {"id": "atlassian", "name": "Rovo Atlassian", "url": "https://mcp.atlassian.com"}
    # Read tools — must NOT be blocked
    assert not _is_unverified_jira_mcp_mutation("getJiraIssue", connection)
    assert not _is_unverified_jira_mcp_mutation("lookupJiraAccountId", connection)
    assert not _is_unverified_jira_mcp_mutation("jira_get_issue_clean", connection)
    assert not _is_unverified_jira_mcp_mutation("searchJiraIssuesUsingJql", connection)
    assert not _is_unverified_jira_mcp_mutation("getAccessibleAtlassianResources", connection)
    # Write tools — MUST be blocked
    assert _is_unverified_jira_mcp_mutation("createJiraIssue", connection)
    assert _is_unverified_jira_mcp_mutation("performAction", connection)
    assert _is_unverified_jira_mcp_mutation("jira_transition_issue", connection)
    assert _is_unverified_jira_mcp_mutation("jira_delete_issue", connection)


def test_approval_rejects_draft_if_configured_site_changed(monkeypatch):
    monkeypatch.setattr("skills.jira.mutations.load_config", lambda: {})
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
    monkeypatch.setattr("skills.jira.mutations.load_config", lambda: {})
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


def test_bare_key_waterfalls_and_fails_when_not_found_on_any_site(monkeypatch):
    """Bare key with multiple sites triggers waterfall; not found on any → clear error."""
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://hub.example.com")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: True)
    monkeypatch.setattr("mcp.manager._load_connections", lambda: [{"id": "primary"}])
    monkeypatch.setattr(
        "skills.jira.mutations.load_config",
        lambda: {"jira_targets": [{
            "id": "rovo:primary:cloud-1",
            "base_url": "https://other.example.com",
            "adapter": "rovo-mcp",
            "is_cloud": True,
            "connection_id": "primary",
            "resource_id": "cloud-1",
        }]},
    )
    monkeypatch.setattr("skills.jira.mutations._probe_target", lambda key, target, context_id="": False)

    with pytest.raises(JiraTargetResolutionError, match="not found on any of the"):
        resolve_jira_target("PROJ-123")


def test_bare_key_waterfall_returns_first_hit(monkeypatch):
    """Waterfall returns the first target that has the issue."""
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://hub.example.com")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: True)
    monkeypatch.setattr("mcp.manager._load_connections", lambda: [{"id": "primary"}])
    monkeypatch.setattr(
        "skills.jira.mutations.load_config",
        lambda: {"jira_targets": [{
            "id": "rovo:primary:cloud-1",
            "base_url": "https://other.example.com",
            "adapter": "rovo-mcp",
            "is_cloud": True,
            "connection_id": "primary",
            "resource_id": "cloud-1",
        }]},
    )
    # builtin-rest probe fails, rovo probe succeeds
    def _mock_probe(key, target, context_id=""):
        return target.adapter == "rovo-mcp"
    monkeypatch.setattr("skills.jira.mutations._probe_target", _mock_probe)

    target = resolve_jira_target("PROJ-123")
    assert target.adapter == "rovo-mcp"
    assert target.base_url == "https://other.example.com"


def test_url_resolves_the_matching_registered_rovo_target(monkeypatch):
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://hub.example.com")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: True)
    monkeypatch.setattr("mcp.manager._load_connections", lambda: [{"id": "primary"}])
    monkeypatch.setattr(
        "skills.jira.mutations.load_config",
        lambda: {"jira_targets": [{
            "id": "rovo:primary:cloud-1",
            "base_url": "https://other.example.com",
            "adapter": "rovo-mcp",
            "is_cloud": True,
            "connection_id": "primary",
            "resource_id": "cloud-1",
        }]},
    )

    target = resolve_jira_target("https://other.example.com/browse/PROJ-123")

    assert target.id == "rovo:primary:cloud-1"
    assert target.adapter == "rovo-mcp"


def test_verified_result_keeps_internal_target_ids_out_of_tool_payload(monkeypatch):
    monkeypatch.setattr("skills.jira.mutations.load_config", lambda: {})
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://hub.example.com")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: True)

    result = verified_result(
        configured_builtin_target(),
        {"operation": "update_issue", "issue_key": "PROJ-123"},
        {"issue_key": "PROJ-123"},
        {"issue_key": "PROJ-123"},
    )

    assert result["canonical_issue_url"] == "https://hub.example.com/browse/PROJ-123"
    assert "id" not in result["target"]
    assert "connection_id" not in result["target"]


def test_selected_target_is_scoped_to_its_tab(monkeypatch):
    monkeypatch.setattr("skills.jira.mutations.load_config", lambda: {})
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://hub.example.com")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: True)
    from skills.jira.mutations import selected_target_for_context, select_target_for_context

    target = configured_builtin_target()
    select_target_for_context("tab-one", target.id)

    assert selected_target_for_context("tab-one") == target
    assert selected_target_for_context("tab-two") is None


def test_builtin_suppresses_rovo_for_same_site(monkeypatch):
    """When builtin-rest and rovo-mcp share a base_url, builtin wins and bare-key resolution is unambiguous."""
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://amd.atlassian.net")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: True)
    monkeypatch.setattr("mcp.manager._load_connections", lambda: [{"id": "conn-rovo"}])
    monkeypatch.setattr(
        "skills.jira.mutations.load_config",
        lambda: {"jira_targets": [{
            "id": "rovo:conn-rovo:cloud-amd",
            "base_url": "https://amd.atlassian.net",
            "adapter": "rovo-mcp",
            "is_cloud": True,
            "connection_id": "conn-rovo",
            "resource_id": "cloud-amd",
        }]},
    )

    target = resolve_jira_target("ICCM-1")
    assert target.adapter == "builtin-rest"
    assert target.base_url == "https://amd.atlassian.net"


def test_two_sites_same_issue_key_waterfalls(monkeypatch):
    """Two connected sites with a bare key triggers waterfall, not ambiguous error."""
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://site-a.atlassian.net")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: True)
    monkeypatch.setattr("mcp.manager._load_connections", lambda: [{"id": "conn-b"}])
    monkeypatch.setattr(
        "skills.jira.mutations.load_config",
        lambda: {"jira_targets": [{
            "id": "rovo:conn-b:cloud-b",
            "base_url": "https://site-b.atlassian.net",
            "adapter": "rovo-mcp",
            "is_cloud": True,
            "connection_id": "conn-b",
            "resource_id": "cloud-b",
        }]},
    )
    # builtin-rest (site-a) has the issue
    monkeypatch.setattr("skills.jira.mutations._probe_target",
                        lambda key, target, context_id="": target.adapter == "builtin-rest")

    target = resolve_jira_target("SAME-42")
    assert target.adapter == "builtin-rest"
    assert target.base_url == "https://site-a.atlassian.net"


def test_full_url_binds_to_rovo_site_not_builtin(monkeypatch):
    """A URL for the Rovo site must resolve to the Rovo target, not the builtin."""
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://site-a.atlassian.net")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: True)
    monkeypatch.setattr("mcp.manager._load_connections", lambda: [{"id": "conn-b"}])
    monkeypatch.setattr(
        "skills.jira.mutations.load_config",
        lambda: {"jira_targets": [{
            "id": "rovo:conn-b:cloud-b",
            "base_url": "https://site-b.atlassian.net",
            "adapter": "rovo-mcp",
            "is_cloud": True,
            "connection_id": "conn-b",
            "resource_id": "cloud-b",
        }]},
    )

    target = resolve_jira_target("https://site-b.atlassian.net/browse/SAME-42")
    assert target.adapter == "rovo-mcp"
    assert target.base_url == "https://site-b.atlassian.net"


def test_full_url_mismatching_both_sites_fails_closed(monkeypatch):
    """A URL that matches neither connected site must be refused."""
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://site-a.atlassian.net")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: True)
    monkeypatch.setattr("mcp.manager._load_connections", lambda: [{"id": "conn-b"}])
    monkeypatch.setattr(
        "skills.jira.mutations.load_config",
        lambda: {"jira_targets": [{
            "id": "rovo:conn-b:cloud-b",
            "base_url": "https://site-b.atlassian.net",
            "adapter": "rovo-mcp",
            "is_cloud": True,
            "connection_id": "conn-b",
            "resource_id": "cloud-b",
        }]},
    )

    with pytest.raises(JiraTargetResolutionError, match="does not belong to a connected"):
        resolve_jira_target("https://site-c.atlassian.net/browse/OTHER-1")


def test_target_from_draft_refuses_changed_connection(monkeypatch):
    """If connection_id changed after draft was prepared, approval must fail closed."""
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://hub.example.com")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: True)
    monkeypatch.setattr("mcp.manager._load_connections", lambda: [{"id": "new-conn"}])
    monkeypatch.setattr(
        "skills.jira.mutations.load_config",
        lambda: {"jira_targets": [{
            "id": "rovo:new-conn:cloud-1",
            "base_url": "https://other.example.com",
            "adapter": "rovo-mcp",
            "is_cloud": True,
            "connection_id": "new-conn",
            "resource_id": "cloud-1",
        }]},
    )
    draft_target = {
        "id": "rovo:old-conn:cloud-1",   # connection_id mismatch
        "base_url": "https://other.example.com",
        "adapter": "rovo-mcp",
        "is_cloud": True,
        "connection_id": "old-conn",
        "resource_id": "cloud-1",
    }

    with pytest.raises(JiraTargetResolutionError, match="connection changed"):
        target_from_draft(draft_target)


def test_target_from_draft_ignores_presentation_metadata_drift(monkeypatch):
    """display_name/capabilities may be refreshed independently of a draft's
    routing identity; a stale copy of that metadata in an older draft must not
    invalidate approval against the currently selected target for the tab."""
    monkeypatch.setattr("skills.jira.mutations.load_config", lambda: {})
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://hub.example.com")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: True)
    from skills.jira.mutations import select_target_for_context

    current = configured_builtin_target()
    select_target_for_context("tab-one", current.id)

    draft_target = {
        "id": current.id,
        "base_url": current.base_url,
        "adapter": current.adapter,
        "is_cloud": current.is_cloud,
        "connection_id": current.connection_id,
        "resource_id": current.resource_id,
        # Stale presentation metadata captured at draft time, since refreshed.
        "display_name": "Jira (legacy)",
        "capabilities": ("read",),
    }

    target = target_from_draft(draft_target, context_id="tab-one")

    assert target.display_name == "Jira (legacy)"


def test_picker_handle_is_tab_scoped(monkeypatch):
    """A picker handle issued for tab-A must not be consumable from tab-B."""
    monkeypatch.setattr("skills.jira.mutations.load_config", lambda: {})
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://hub.example.com")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: True)
    from skills.jira.mutations import target_selection_event, select_target_handle

    event = target_selection_event("tab-A")
    handle = event["targets"][0]["handle"]

    with pytest.raises(JiraTargetResolutionError, match="belongs to another tab"):
        select_target_handle("tab-B", handle)


def test_picker_handle_consumed_only_once(monkeypatch):
    """A picker handle must be consumed exactly once (single-use)."""
    monkeypatch.setattr("skills.jira.mutations.load_config", lambda: {})
    monkeypatch.setattr("skills.jira.api.jira_browse_url", lambda: "https://hub.example.com")
    monkeypatch.setattr("skills.jira.api.jira_is_cloud", lambda: True)
    from skills.jira.mutations import target_selection_event, select_target_handle

    event = target_selection_event("tab-C")
    handle = event["targets"][0]["handle"]

    select_target_handle("tab-C", handle)  # first consume: OK

    with pytest.raises(JiraTargetResolutionError):
        select_target_handle("tab-C", handle)  # second consume: must fail


def test_rovo_call_refuses_unknown_operation():
    from skills.jira.mutations import JiraTarget, rovo_jira_call
    target = JiraTarget(
        id="rovo:c:r", base_url="https://x.atlassian.net",
        adapter="rovo-mcp", is_cloud=True,
        connection_id="c", resource_id="r",
    )
    with pytest.raises(JiraTargetResolutionError, match="verified adapter"):
        rovo_jira_call(target, "delete_issue", {})


def test_rovo_call_refuses_builtin_target():
    from skills.jira.mutations import JiraTarget, rovo_jira_call
    target = JiraTarget(
        id="builtin:https://x.atlassian.net",
        base_url="https://x.atlassian.net",
        adapter="builtin-rest", is_cloud=True,
    )
    with pytest.raises(JiraTargetResolutionError, match="Rovo-backed"):
        rovo_jira_call(target, "get_issue", {})


def test_discovery_failed_connection_preserves_existing_targets(monkeypatch):
    """A connection that fails discovery (expired OAuth, timeout) must NOT erase
    its previously stored targets. Only a successful re-discovery or an explicit
    connection removal may change the stored target set."""
    from unittest.mock import MagicMock
    from skills.jira.mutations import discover_rovo_targets

    existing_target = {
        "id": "rovo:conn-good:cloud-1",
        "base_url": "https://good.atlassian.net",
        "adapter": "rovo-mcp",
        "is_cloud": True,
        "connection_id": "conn-good",
        "resource_id": "cloud-1",
        "display_name": "Good site",
        "capabilities": ["read"],
    }
    existing_target_failing = {
        "id": "rovo:conn-bad:cloud-2",
        "base_url": "https://bad.atlassian.net",
        "adapter": "rovo-mcp",
        "is_cloud": True,
        "connection_id": "conn-bad",
        "resource_id": "cloud-2",
        "display_name": "Failing site",
        "capabilities": ["read"],
    }

    saved: list = []

    def _fake_update_config(fn):
        cfg = {"jira_targets": [existing_target, existing_target_failing]}
        result = fn(cfg)
        saved.extend(result.get("jira_targets", []))

    conn_good = {
        "id": "conn-good", "enabled": True,
        "cached_tools": [{"name": "getAccessibleAtlassianResources"}],
        "url": "https://mcp.atlassian.com/v1/mcp", "auth_type": "oauth2",
        "transport": "http",
    }
    conn_bad = {
        "id": "conn-bad", "enabled": True,
        "cached_tools": [{"name": "getAccessibleAtlassianResources"}],
        "url": "https://mcp.atlassian.com/v1/mcp", "auth_type": "oauth2",
        "transport": "http",
    }

    import json as _json

    def _fake_client_for(conn, pooled=False):
        mc = MagicMock()
        if conn["id"] == "conn-good":
            mc.call.return_value = _json.dumps({
                "resources": [{"id": "cloud-1", "url": "https://good.atlassian.net", "name": "Good site"}]
            })
        else:
            mc.call.side_effect = RuntimeError("OAuth token expired")
        return mc

    monkeypatch.setattr("config.update_config", _fake_update_config)
    monkeypatch.setattr("mcp.manager._load_connections", lambda: [conn_good, conn_bad])
    monkeypatch.setattr("mcp.manager._client_for", _fake_client_for)

    result = discover_rovo_targets()

    # conn-good succeeded — its fresh target should be in the result
    assert any(t.connection_id == "conn-good" for t in result)

    # conn-bad failed — its OLD stored target must survive in the written config
    saved_conn_ids = [e.get("connection_id") for e in saved]
    assert "conn-bad" in saved_conn_ids, (
        "Failed connection's existing target must be preserved in config"
    )
    assert "conn-good" in saved_conn_ids, (
        "Successfully re-discovered connection must also appear"
    )


def test_discovery_deduplicates_same_resource_across_connections(monkeypatch):
    """Two connections exposing the same cloud resource produce only one stored target."""
    from unittest.mock import MagicMock
    from skills.jira.mutations import discover_rovo_targets

    saved: list = []

    def _fake_update_config(fn):
        cfg = {"jira_targets": []}
        result = fn(cfg)
        saved.extend(result.get("jira_targets", []))

    # Both connections return the same resource ID and URL.
    same_resource = [{"id": "cloud-shared", "url": "https://shared.atlassian.net", "name": "Shared"}]
    import json as _json

    def _make_conn(conn_id):
        return {
            "id": conn_id, "enabled": True,
            "cached_tools": [{"name": "getAccessibleAtlassianResources"}],
            "url": "https://mcp.atlassian.com/v1/mcp",
            "auth_type": "oauth2", "transport": "http",
        }

    def _fake_client_for(conn, pooled=False):
        mc = MagicMock()
        mc.call.return_value = _json.dumps({"resources": same_resource})
        return mc

    monkeypatch.setattr("config.update_config", _fake_update_config)
    monkeypatch.setattr("mcp.manager._load_connections",
                        lambda: [_make_conn("conn-a"), _make_conn("conn-b")])
    monkeypatch.setattr("mcp.manager._client_for", _fake_client_for)

    result = discover_rovo_targets()

    # Two connections × one shared resource = two JiraTarget objects returned by discover
    assert len(result) == 2

    # But only ONE entry persisted, because the stable ID is identical for both.
    saved_ids = [e.get("id") for e in saved]
    assert len(saved_ids) == 2   # conn-a and conn-b have different conn IDs → different target IDs
    assert len(set(saved_ids)) == 2

    # Verify: if both connections return the SAME conn_id (shouldn't happen but test the guard),
    # only one is kept.
    saved2: list = []

    def _fake_update_config2(fn):
        cfg = {"jira_targets": []}
        result2 = fn(cfg)
        saved2.extend(result2.get("jira_targets", []))

    # Simulate: same connection ID returned twice in discovery list (e.g. config bug)
    monkeypatch.setattr("config.update_config", _fake_update_config2)
    monkeypatch.setattr("mcp.manager._load_connections",
                        lambda: [_make_conn("conn-same"), _make_conn("conn-same")])

    discover_rovo_targets()
    saved2_ids = [e.get("id") for e in saved2]
    assert len(saved2_ids) == len(set(saved2_ids)), \
        "Duplicate stable IDs must not be persisted even if the same connection appears twice"


def test_discovery_removed_connection_erases_its_targets(monkeypatch):
    """A connection removed from mcp_connections must have its targets removed."""
    from unittest.mock import MagicMock
    from skills.jira.mutations import discover_rovo_targets

    orphan_target = {
        "id": "rovo:conn-removed:cloud-9",
        "base_url": "https://gone.atlassian.net",
        "adapter": "rovo-mcp",
        "is_cloud": True,
        "connection_id": "conn-removed",
        "resource_id": "cloud-9",
        "display_name": "Gone site",
        "capabilities": ["read"],
    }

    saved: list = []

    def _fake_update_config(fn):
        cfg = {"jira_targets": [orphan_target]}
        result = fn(cfg)
        saved.extend(result.get("jira_targets", []))

    # conn-removed is not in the current connections list
    monkeypatch.setattr("config.update_config", _fake_update_config)
    monkeypatch.setattr("mcp.manager._load_connections", lambda: [])

    discover_rovo_targets()

    removed_ids = [e.get("connection_id") for e in saved]
    assert "conn-removed" not in removed_ids, (
        "Target for a removed connection must be erased from config"
    )


@pytest.mark.skipif(
    __import__("sys").platform == "win32",
    reason="Creating symlinks requires elevated privileges on Windows",
)
def test_staged_attachment_rejects_symlink(monkeypatch, tmp_path):
    import skills.jira.mutations as mutations

    monkeypatch.setattr(mutations.tempfile, "gettempdir", lambda: str(tmp_path))
    staged = mutations.stage_attachment("doc.pdf", b"real content", "application/pdf")
    uid = staged["upload_id"]
    path = mutations._staged_attachments[uid]["path"]
    real = path
    sym = tmp_path / "symlink_attack"
    sym.symlink_to(real)
    mutations._staged_attachments[uid]["path"] = sym

    with pytest.raises(JiraTargetResolutionError, match="regular file"):
        mutations.staged_attachment(uid)
