"""A direct-REST Jira write that Jira rejects over its fields is retried once through
Rovo on the same site. Anything else (timeouts, 5xx, 401/403/404, no Rovo for the
site) is never retried, and the result says which path actually ran."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from unittest.mock import patch

from app import app
from fastapi.testclient import TestClient
from skills import _drafts
from skills.jira.mutations import JiraTarget, rovo_write_fallback

SITE = "https://jira.example.com"


def _csrf():
    from security import get_csrf_token
    return get_csrf_token("testserver")


def _approve(client, draft_id):
    return client.post(f"/api/drafts/{draft_id}/approve", headers={"X-CSRF-Token": _csrf()}, json=None)


def _direct():
    return JiraTarget(id=f"builtin:{SITE}", base_url=SITE, adapter="builtin-rest", is_cloud=True)


def _rovo():
    return JiraTarget(id="rovo:conn-1:cloud-1", base_url=SITE, adapter="rovo-mcp", is_cloud=True,
                      connection_id="conn-1", resource_id="cloud-1")


ISSUE = {"key": "PROJ-1", "fields": {
    "summary": "Fix it", "labels": ["gator"], "comment": {"comments": [{"id": "c1"}]},
    "issuelinks": [{"id": "l1", "type": {"name": "Blocks"}, "outwardIssue": {"key": "OTHER-2"}}],
}}


def setup_function(function):
    _drafts._pending_drafts.clear()


def _run(draft_id, rest, rovo, rovo_targets=None):
    """Approve ``draft_id`` with REST handled by ``rest`` and Rovo by ``rovo``."""
    rovo_targets = [_rovo()] if rovo_targets is None else rovo_targets
    client = TestClient(app)
    with patch("skills.jira.mutations.available_targets", return_value=[_direct()]), \
         patch("skills.jira.mutations._registered_targets", return_value=rovo_targets), \
         patch("skills.jira.api.jira_browse_url", return_value=SITE), \
         patch("skills.jira.api.jira_api_for_target", side_effect=rest), \
         patch("skills.jira.mutations.rovo_jira_call", side_effect=rovo):
        return _approve(client, draft_id)


def _rest_rejecting(method, path_part, status="400"):
    def _api(target, verb, path, body=None):
        if verb == method and path_part in path:
            raise RuntimeError(f'HTTP {status}: {{"errors": {{"labels": "Field \'labels\' cannot be set"}}}}')
        if verb == "GET":
            return ISSUE
        return {}
    return _api


def _rovo_ok(calls):
    def _call(target, operation, arguments):
        calls.append((target.adapter, operation, dict(arguments)))
        if operation == "create_issue":
            return {"key": "PROJ-1"}
        if operation == "add_comment":
            return {"id": "c1"}
        return {"data": ISSUE}
    return _call


def _comment_draft():
    return _drafts.create_draft(
        "jira-comment", {"issue_key": "PROJ-1", "comment": "hello", "jira_target": _direct().to_dict()}, {})


def _create_draft():
    return _drafts.create_draft(
        "jira-create",
        {"project": "PROJ", "summary": "Fix it", "issue_type": "Task", "description": "d", "priority": "",
         "extra_fields": {"labels": ["gator"]}, "parent_key": "", "assignee_account_id": "",
         "jira_target": _direct().to_dict()}, {})


def _update_draft():
    return _drafts.create_draft(
        "jira-update",
        {"issue_key": "PROJ-1", "fields": {"labels": ["gator"]}, "jira_target": _direct().to_dict()}, {})


def _link_draft():
    return _drafts.create_draft(
        "jira-link",
        {"issue_key": "PROJ-1", "other_key": "OTHER-2", "link_type": "Blocks", "before_link_ids": [],
         "payload": {"type": {"name": "Blocks"}, "inwardIssue": {"key": "OTHER-2"}, "outwardIssue": {"key": "PROJ-1"}},
         "jira_target": _direct().to_dict()}, {})


def test_comment_rejected_by_rest_is_retried_through_rovo_and_reported():
    calls = []
    r = _run(_comment_draft(), _rest_rejecting("POST", "comment"), _rovo_ok(calls))
    assert r.status_code == 200, r.text
    body = r.json()
    assert [c[:2] for c in calls if c[1] == "add_comment"] == [("rovo-mcp", "add_comment")]
    assert body["fallback"]["from"] == "builtin-rest" and body["fallback"]["to"] == "rovo-mcp"
    assert "HTTP 400" in body["fallback"]["reason"]
    assert body["target"]["adapter"] == "rovo-mcp"
    assert body["verified"]["present"] is True


def test_create_rejected_by_rest_is_retried_with_the_same_fields_through_rovo():
    calls = []
    r = _run(_create_draft(), _rest_rejecting("POST", "issue"), _rovo_ok(calls))
    assert r.status_code == 200, r.text
    assert r.json()["issue_key"] == "PROJ-1"
    adapter, _, args = next(c for c in calls if c[1] == "create_issue")
    assert adapter == "rovo-mcp"
    assert args["projectKey"] == "PROJ" and args["summary"] == "Fix it"
    assert args["additional_fields"] == {"labels": ["gator"]}
    assert r.json()["fallback"]["to"] == "rovo-mcp"


def test_update_rejected_by_rest_is_retried_through_rovo_and_verified():
    calls = []
    r = _run(_update_draft(), _rest_rejecting("PUT", "issue/PROJ-1"), _rovo_ok(calls))
    assert r.status_code == 200, r.text
    assert ("rovo-mcp", "update_issue", {"issueIdOrKey": "PROJ-1", "fields": {"labels": ["gator"]}}) in calls
    assert r.json()["ok"] is True and r.json()["fallback"]["to"] == "rovo-mcp"


def test_link_rejected_by_rest_is_retried_through_rovo():
    calls = []
    r = _run(_link_draft(), _rest_rejecting("POST", "issueLink"), _rovo_ok(calls))
    assert r.status_code == 200, r.text
    assert any(c[:2] == ("rovo-mcp", "create_link") for c in calls)
    assert r.json()["fallback"]["to"] == "rovo-mcp"


def test_server_errors_and_auth_failures_are_not_retried():
    for status in ("500", "502", "401", "403", "404"):
        _drafts._pending_drafts.clear()
        calls = []
        r = _run(_comment_draft(), _rest_rejecting("POST", "comment", status), _rovo_ok(calls))
        assert r.status_code >= 400, (status, r.text)
        assert not any(c[1] == "add_comment" for c in calls), status


def test_timeout_is_not_retried():
    def _rest(target, verb, path, body=None):
        if verb == "POST":
            raise RuntimeError("HTTPSConnectionPool: Read timed out.")
        return ISSUE

    calls = []
    r = _run(_comment_draft(), _rest, _rovo_ok(calls))
    assert r.status_code >= 400
    assert not any(c[1] == "add_comment" for c in calls)


def test_no_rovo_target_for_the_site_means_no_retry_and_the_original_error():
    calls = []
    r = _run(_create_draft(), _rest_rejecting("POST", "issue"), _rovo_ok(calls), rovo_targets=[])
    assert r.status_code == 422
    assert not calls


def test_rovo_target_for_a_different_site_is_never_used():
    other = JiraTarget(id="rovo:conn-1:cloud-2", base_url="https://other.atlassian.net", adapter="rovo-mcp",
                       is_cloud=True, connection_id="conn-1", resource_id="cloud-2")
    calls = []
    r = _run(_comment_draft(), _rest_rejecting("POST", "comment"), _rovo_ok(calls), rovo_targets=[other])
    assert r.status_code >= 400
    assert not calls


def test_when_the_retry_also_fails_both_reasons_are_reported_and_the_draft_survives():
    def _rovo_fail(target, operation, arguments):
        if operation == "add_comment":
            raise RuntimeError("Rovo refused it")
        return {"data": ISSUE}

    draft_id = _comment_draft()
    r = _run(draft_id, _rest_rejecting("POST", "comment"), _rovo_fail)
    assert r.status_code >= 400
    assert "HTTP 400" in r.text and "Rovo refused it" in r.text
    assert draft_id in _drafts._pending_drafts


def test_rovo_write_fallback_only_for_direct_rest_field_rejections():
    direct, rovo = _direct(), _rovo()
    with patch("skills.jira.mutations._registered_targets", return_value=[rovo]):
        assert rovo_write_fallback(direct, "HTTP 400: {}") == rovo
        assert rovo_write_fallback(direct, "HTTP 422: {}") == rovo
        assert rovo_write_fallback(direct, "HTTP 401: {}") is None
        assert rovo_write_fallback(direct, "HTTP 500: {}") is None
        assert rovo_write_fallback(direct, "timed out") is None
        assert rovo_write_fallback(rovo, "HTTP 400: {}") is None


def test_comment_id_is_read_from_commentId_when_rovo_v2_omits_id():
    def _rovo(target, operation, arguments):
        if operation == "add_comment":
            return {"message": "Comment added", "commentId": "c1"}
        return {"data": ISSUE}

    r = _run(_comment_draft(), _rest_rejecting("POST", "comment"), _rovo)
    assert r.status_code == 200, r.text
    assert r.json()["verified"]["comment_id"] == "c1" and r.json()["verified"]["present"] is True
