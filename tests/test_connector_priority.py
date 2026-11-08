"""Connector priority is invariant for Jira reads and writes:
1) direct Atlassian API, 2) official Atlassian MCP, 3) any other connector, last.

Capability discovery, list order and discovery order never reorder it, and the one
sanctioned step from the API to the MCP (a 400/422 field rejection on a write) stays on
the same site and is reported."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from unittest.mock import patch

import pytest
from app import app
from fastapi.testclient import TestClient
from skills import _drafts
from skills.jira import mutations
from skills.jira.mutations import (
    CONNECTOR_PRIORITY,
    JiraTarget,
    _migrate_legacy_target,
    _waterfall_resolve,
    atlassian_mcp_write_fallback,
    available_targets,
    connector_rank,
)

DIRECT_SITE = "https://direct.example.com"
MCP_SITE = "https://mcp.example.com"
OTHER = JiraTarget(id="other:x", base_url="https://other.example.com", adapter="some-other-connector", is_cloud=True)


def _direct(site=DIRECT_SITE, capabilities=()):
    return JiraTarget(id=f"builtin:{site}", base_url=site, adapter="builtin-rest", is_cloud=True,
                      capabilities=capabilities)


def _mcp(site=MCP_SITE, capabilities=("read", "create", "update", "watcher", "attachment")):
    return JiraTarget(id=f"atlassian-mcp:conn-1:{site}", base_url=site, adapter="atlassian-mcp", is_cloud=True,
                      connection_id="conn-1", resource_id="cloud-1", capabilities=capabilities)


@pytest.fixture(autouse=True)
def _fresh_probe_cache():
    mutations._probe_cache.clear()
    _drafts._pending_drafts.clear()
    yield
    mutations._probe_cache.clear()


def test_priority_constant_is_direct_then_atlassian_mcp():
    assert CONNECTOR_PRIORITY == ("builtin-rest", "atlassian-mcp")


def test_adapters_rank_direct_then_atlassian_mcp_then_everything_else():
    assert connector_rank("builtin-rest") < connector_rank("atlassian-mcp") < connector_rank("some-other-connector")
    assert connector_rank("") == connector_rank("anything-unlisted") == len(CONNECTOR_PRIORITY)


@pytest.mark.parametrize("order", [
    [_direct(), _mcp(), OTHER],
    [OTHER, _mcp(), _direct()],
    [_mcp(), OTHER, _direct()],
])
def test_waterfall_prefers_direct_whatever_order_targets_arrive_in(order):
    with patch.object(mutations, "_probe_target", return_value=True):
        assert _waterfall_resolve("PROJ-1", order).adapter == "builtin-rest"


def test_capabilities_reported_by_the_mcp_never_outrank_the_direct_api():
    rich_mcp = _mcp(capabilities=("read", "create", "update", "watcher", "attachment", "everything"))
    bare_direct = _direct(capabilities=())
    with patch.object(mutations, "_probe_target", return_value=True):
        assert _waterfall_resolve("PROJ-1", [rich_mcp, bare_direct]).adapter == "builtin-rest"


def test_other_connectors_are_only_reached_after_direct_and_mcp_miss():
    probed = []

    def _probe(key, target, context_id=""):
        probed.append(target.adapter)
        return target.adapter == "some-other-connector"

    with patch.object(mutations, "_probe_target", side_effect=_probe):
        picked = _waterfall_resolve("PROJ-1", [OTHER, _mcp(), _direct()])
    assert picked.adapter == "some-other-connector"
    assert probed[:2] == ["builtin-rest", "atlassian-mcp"]


def test_a_read_that_the_direct_api_answers_never_calls_the_atlassian_mcp():
    mcp_calls = []

    def _rest(target, method, path, body=None):
        return {"key": "PROJ-1", "id": "1"}

    def _mcp_call(target, operation, arguments):
        mcp_calls.append(operation)
        return {"data": {"key": "PROJ-1"}}

    with patch.object(mutations, "available_targets", return_value=[_mcp(), _direct()]), \
         patch("skills.jira.api.jira_api_for_target", side_effect=_rest), \
         patch.object(mutations, "atlassian_mcp_jira_call", side_effect=_mcp_call):
        target = mutations.resolve_jira_target("PROJ-1")
    assert target.adapter == "builtin-rest"
    assert mcp_calls == []


def test_a_read_the_direct_api_cannot_find_goes_to_the_atlassian_mcp():
    def _rest(target, method, path, body=None):
        raise RuntimeError("HTTP 404: not found")

    def _mcp_call(target, operation, arguments):
        return {"data": {"key": "PROJ-1"}}

    with patch.object(mutations, "available_targets", return_value=[_direct(), _mcp()]), \
         patch("skills.jira.api.jira_api_for_target", side_effect=_rest), \
         patch.object(mutations, "atlassian_mcp_jira_call", side_effect=_mcp_call):
        assert mutations.resolve_jira_target("PROJ-1").adapter == "atlassian-mcp"


def test_available_targets_lists_direct_before_mcp_regardless_of_discovery_order():
    mcp_a, mcp_b = _mcp("https://a.example.com"), _mcp("https://b.example.com")
    with patch.object(mutations, "_registered_targets", return_value=[mcp_b, mcp_a]), \
         patch.object(mutations, "configured_builtin_target", return_value=_direct()), \
         patch.object(mutations, "_extra_builtin_targets", return_value=[]):
        adapters = [t.adapter for t in available_targets()]
    assert adapters == ["builtin-rest", "atlassian-mcp", "atlassian-mcp"]


def test_a_site_reachable_both_ways_keeps_only_the_direct_target():
    same_site = _mcp(DIRECT_SITE)
    with patch.object(mutations, "_registered_targets", return_value=[same_site]), \
         patch.object(mutations, "configured_builtin_target", return_value=_direct()), \
         patch.object(mutations, "_extra_builtin_targets", return_value=[]):
        targets = available_targets()
    assert [t.adapter for t in targets] == ["builtin-rest"]


@pytest.mark.parametrize("error", ["HTTP 401: x", "HTTP 403: x", "HTTP 404: x", "HTTP 500: x", "HTTP 503: x",
                                   "timed out", "Connection reset"])
def test_only_a_field_rejection_lets_a_write_step_down_to_the_atlassian_mcp(error):
    with patch.object(mutations, "_registered_targets", return_value=[_mcp(DIRECT_SITE)]):
        assert atlassian_mcp_write_fallback(_direct(), error) is None


@pytest.mark.parametrize("error", ["HTTP 400: {}", "HTTP 422: {}"])
def test_a_field_rejection_steps_down_to_the_mcp_on_the_same_site_only(error):
    same, elsewhere = _mcp(DIRECT_SITE), _mcp("https://elsewhere.example.com")
    with patch.object(mutations, "_registered_targets", return_value=[elsewhere, same]):
        assert atlassian_mcp_write_fallback(_direct(), error) == same
    with patch.object(mutations, "_registered_targets", return_value=[elsewhere]):
        assert atlassian_mcp_write_fallback(_direct(), error) is None


def test_the_mcp_never_steps_back_up_or_sideways():
    with patch.object(mutations, "_registered_targets", return_value=[_mcp(DIRECT_SITE)]):
        assert atlassian_mcp_write_fallback(_mcp(DIRECT_SITE), "HTTP 400: {}") is None
        assert atlassian_mcp_write_fallback(OTHER, "HTTP 400: {}") is None


def _csrf():
    from security import get_csrf_token
    return get_csrf_token("testserver")


def _approve_update(rest, mcp):
    draft_id = _drafts.create_draft(
        "jira-update",
        {"issue_key": "PROJ-1", "fields": {"labels": ["gator"]}, "jira_target": _direct(DIRECT_SITE).to_dict()}, {})
    with patch.object(mutations, "available_targets", return_value=[_direct(DIRECT_SITE)]), \
         patch.object(mutations, "_registered_targets", return_value=[_mcp(DIRECT_SITE)]), \
         patch("skills.jira.api.jira_browse_url", return_value=DIRECT_SITE), \
         patch("skills.jira.api.jira_api_for_target", side_effect=rest), \
         patch.object(mutations, "atlassian_mcp_jira_call", side_effect=mcp):
        return TestClient(app).post(
            f"/api/drafts/{draft_id}/approve", headers={"X-CSRF-Token": _csrf()}, json=None)


_ISSUE = {"key": "PROJ-1", "fields": {"labels": ["gator"], "summary": "s"}}


def test_a_write_hits_the_direct_api_first_and_never_touches_the_mcp_when_it_succeeds():
    order = []

    def _rest(target, method, path, body=None):
        order.append(("rest", method))
        return _ISSUE if method == "GET" else {}

    def _mcp_call(target, operation, arguments):
        order.append(("mcp", operation))
        return {"data": _ISSUE}

    r = _approve_update(_rest, _mcp_call)
    assert r.status_code == 200, r.text
    assert order and all(kind == "rest" for kind, _ in order)
    assert "fallback" not in r.json()


def test_a_field_rejection_tries_the_direct_api_before_the_mcp_and_reports_the_step_down():
    order = []

    def _rest(target, method, path, body=None):
        order.append(("rest", method))
        if method == "PUT":
            raise RuntimeError('HTTP 400: {"errors": {"labels": "cannot be set"}}')
        return _ISSUE

    def _mcp_call(target, operation, arguments):
        order.append(("mcp", operation))
        return {"data": _ISSUE}

    r = _approve_update(_rest, _mcp_call)
    assert r.status_code == 200, r.text
    assert ("rest", "PUT") in order and any(kind == "mcp" for kind, _ in order)
    assert order.index(("rest", "PUT")) < next(i for i, (k, _) in enumerate(order) if k == "mcp")
    fallback = r.json()["fallback"]
    assert (fallback["from"], fallback["to"]) == ("builtin-rest", "atlassian-mcp")
    assert "HTTP 400" in fallback["reason"]


@pytest.mark.parametrize("status", ["401", "403", "404", "500"])
def test_other_rest_failures_do_not_elevate_to_the_mcp(status):
    mcp_calls = []

    def _rest(target, method, path, body=None):
        if method == "PUT":
            raise RuntimeError(f"HTTP {status}: nope")
        return _ISSUE

    r = _approve_update(_rest, lambda t, o, a: mcp_calls.append(o) or {"data": _ISSUE})
    assert r.status_code >= 400
    assert mcp_calls == []


def test_the_chat_prompt_states_the_three_tier_order():
    import shared
    from routes.chat import _append_jira_instance_context

    with patch.dict(shared.SKILL_TOOLS_MAP, {"jira": {"jira_get_issue"}}):
        prompt = _append_jira_instance_context("", ["jira"], {"jira_base_url": DIRECT_SITE})
    text = " ".join(prompt.split())
    assert "CONNECTOR PRIORITY" in text
    one, two, three = (text.index(s) for s in ("1) the direct Atlassian API", "2) the official Atlassian MCP",
                                              "3) any other connector"))
    assert one < two < three
    assert "rovo" not in text.lower()


def test_a_target_saved_under_the_old_rovo_name_still_loads_as_an_atlassian_mcp_target():
    legacy = {"id": "rovo:conn-1:cloud-1", "base_url": MCP_SITE, "adapter": "rovo-mcp", "is_cloud": True,
              "connection_id": "conn-1", "resource_id": "cloud-1"}
    migrated = _migrate_legacy_target(legacy)
    assert migrated["adapter"] == "atlassian-mcp"
    assert migrated["id"] == "atlassian-mcp:conn-1:cloud-1"
    assert legacy["adapter"] == "rovo-mcp"

    with patch.object(mutations, "load_config", return_value={"jira_targets": [legacy]}), \
         patch("mcp.manager._load_connections", return_value=[{"id": "conn-1"}]):
        loaded = mutations._registered_targets()
    assert [(t.adapter, t.id) for t in loaded] == [("atlassian-mcp", "atlassian-mcp:conn-1:cloud-1")]


def test_current_targets_pass_through_migration_untouched():
    current = {"id": "atlassian-mcp:c:r", "adapter": "atlassian-mcp"}
    assert _migrate_legacy_target(current) is current


def test_the_jira_skill_documents_the_same_priority():
    text = (pathlib.Path(mutations.__file__).parent / "SKILL.md").read_text(encoding="utf-8")
    text = " ".join(text.split())
    one, two, three = (text.index(s) for s in ("1) the direct Atlassian API", "2) the official Atlassian MCP",
                                              "3) any other connector"))
    assert one < two < three
    assert "rovo" not in text.lower()
