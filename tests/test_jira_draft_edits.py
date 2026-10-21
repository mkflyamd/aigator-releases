"""Approval-card edits for Jira drafts (`edited_fields` on /api/drafts/{id}/approve)."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app
from skills import _drafts
from skills.jira.mutations import JiraTarget


def _approve(client, draft_id, body=None):
    from security import get_csrf_token
    return client.post(
        f"/api/drafts/{draft_id}/approve",
        headers={"X-CSRF-Token": get_csrf_token()},
        json=body,
    )


def _target() -> dict:
    return JiraTarget(
        id="builtin:https://jira.example.com",
        base_url="https://jira.example.com",
        adapter="builtin-rest",
        is_cloud=True,
    ).to_dict()


def setup_function(function):
    _drafts._pending_drafts.clear()


class _Api:
    """Fake jira_api_for_target that records every write."""

    def __init__(self, summary="Edited summary"):
        self.writes = []
        self.summary = summary

    def __call__(self, target, method, path, body=None):
        if method in ("POST", "PUT"):
            self.writes.append((method, path, body))
        if method == "POST" and path == "issue":
            return {"key": "PROJ-1"}
        if method == "POST" and path.endswith("/comment"):
            return {"id": "c1"}
        if method == "GET":
            return {"fields": {"summary": self.summary, "comment": {"comments": [{"id": "c1"}]}}}
        return {}


def _run(did, body):
    api = _Api()
    with patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
         patch("skills.jira.api.jira_api_for_target", side_effect=api):
        r = _approve(TestClient(app), did, body)
    return r, api


def _comment_draft():
    return _drafts.create_draft(
        "jira-comment",
        {"issue_key": "PROJ-1", "comment": "Original.", "jira_target": _target()},
        {},
    )


def _create_draft():
    return _drafts.create_draft(
        "jira-create",
        {
            "project": "PROJ", "summary": "Original summary", "issue_type": "Task",
            "description": "Original description", "jira_target": _target(),
        },
        {},
    )


def _update_draft(fields):
    return _drafts.create_draft(
        "jira-update",
        {"issue_key": "PROJ-1", "fields": fields, "jira_target": _target()},
        {},
    )


def test_edited_comment_is_what_gets_posted():
    r, api = _run(_comment_draft(), {"edited_fields": {"comment": "Thanks for the updates!"}})
    assert r.status_code == 200, r.text
    (_, path, body), = [w for w in api.writes if w[1].endswith("/comment")]
    assert "Thanks for the updates!" in str(body)
    assert "Original." not in str(body)


def test_unedited_comment_posts_the_draft_text():
    r, api = _run(_comment_draft(), {})
    assert r.status_code == 200, r.text
    assert "Original." in str(api.writes[0][2])


def test_empty_comment_is_rejected_and_the_draft_survives():
    did = _comment_draft()
    r, api = _run(did, {"edited_fields": {"comment": "   "}})
    assert r.status_code == 400
    assert api.writes == []
    assert _drafts.get_draft(did) is not None


def test_fields_outside_the_whitelist_are_rejected():
    did = _comment_draft()
    r, api = _run(did, {"edited_fields": {"issue_key": "OTHER-9"}})
    assert r.status_code == 400
    assert api.writes == []
    assert _drafts.get_draft(did)["params"]["issue_key"] == "PROJ-1"


def test_edited_create_fields_reach_the_new_issue():
    r, api = _run(_create_draft(), {"edited_fields": {"summary": "Edited summary", "description": "New body"}})
    assert r.status_code == 200, r.text
    (_, _, body), = [w for w in api.writes if w[1] == "issue"]
    assert body["fields"]["summary"] == "Edited summary"
    assert "New body" in str(body["fields"]["description"])
    assert body["fields"]["project"] == {"key": "PROJ"}


def test_multiline_summary_is_rejected():
    r, api = _run(_create_draft(), {"edited_fields": {"summary": "a\nb"}})
    assert r.status_code == 400
    assert api.writes == []


def test_edited_update_summary_replaces_the_staged_value():
    did = _update_draft({"summary": "Staged summary"})
    r, api = _run(did, {"edited_fields": {"summary": "Edited summary"}})
    assert r.status_code == 200, r.text
    (_, path, body), = [w for w in api.writes if w[0] == "PUT"]
    assert path == "issue/PROJ-1"
    assert body == {"fields": {"summary": "Edited summary"}}


def test_update_cannot_add_a_field_it_was_not_staged_with():
    did = _update_draft({"summary": "Staged summary"})
    r, api = _run(did, {"edited_fields": {"description": "sneaky"}})
    assert r.status_code == 400
    assert api.writes == []


def test_edits_do_not_apply_to_other_draft_types():
    did = _drafts.create_draft(
        "jira-transition",
        {"issue_key": "PROJ-1", "transition_name": "Done", "expected_status": "Done",
         "payload": {"transition": {"id": "21"}}, "jira_target": _target()},
        {},
    )
    r, api = _run(did, {"edited_fields": {"comment": "x"}})
    assert r.status_code == 400
    assert api.writes == []
