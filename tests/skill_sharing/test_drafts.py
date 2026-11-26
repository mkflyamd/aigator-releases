from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import app
from security import get_csrf_token
from skills._drafts import get_draft
from skills._sharing import drafts

PEOPLE = [{"name": "Ann Lee", "email": "A@Contoso.com"}, {"name": "Bo Chen", "email": "b@contoso.com"}]


def _build(people=PEOPLE):
    return drafts.build(skill_id="my-skill", people=people, message="Link: aigator://share?d=abc")


def _data(people=PEOPLE):
    return _build(people)["drafts"][0]["data"]


def _approve(draft_id, body=None):
    return TestClient(app).post(
        f"/api/drafts/{draft_id}/approve",
        headers={"X-CSRF-Token": get_csrf_token("testserver")},
        json=body,
    )


def test_makes_one_email_draft_for_everyone():
    out = _build()
    assert out["unmatched"] == []
    assert len(out["drafts"]) == 1
    data = out["drafts"][0]["data"]
    assert data["to"] == "a@contoso.com,b@contoso.com"
    assert data["to_names"] == "Ann Lee,Bo Chen"
    assert "my-skill" in data["subject"]
    assert data["body"] == "Link: aigator://share?d=abc"


def test_names_are_left_out_unless_everyone_has_one():
    data = _data([{"name": "Ann Lee", "email": "a@contoso.com"}, {"email": "b@contoso.com"}])
    assert data["to_names"] == ""


def test_a_comma_in_a_name_cannot_shift_the_names_onto_other_addresses():
    data = _data([{"name": "Lee, Ann", "email": "a@contoso.com"}, {"name": "Bo", "email": "b@contoso.com"}])
    assert data["to_names"] == "Lee Ann,Bo"


def test_the_draft_is_locked_to_the_exact_text_that_was_drafted():
    data = _data()
    stored = get_draft(data["draft_id"])
    assert data["locked"] is True
    assert stored["share_digest"] == drafts.content_digest(stored["params"])


def _approve_with_graph(draft_id, body=None):
    gc = MagicMock()
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        return _approve(draft_id, body), gc


def test_approving_as_shown_sends_the_exact_text():
    draft_id = _data()["draft_id"]
    res, gc = _approve_with_graph(draft_id, {"edited_subject": get_draft(draft_id)["params"]["subject"]})
    assert res.status_code == 200, res.text
    sent = gc.post.call_args.args[1]["message"]
    assert "aigator://share?d=abc" in sent["body"]["content"]
    assert [r["emailAddress"]["address"] for r in sent["toRecipients"]] == ["a@contoso.com", "b@contoso.com"]
    assert get_draft(draft_id) is None


def test_an_edited_message_is_refused_and_nothing_is_sent():
    draft_id = _data()["draft_id"]
    for edit in (
        {"edited_message": "Click http://evil.example"},
        {"edited_html": "<p>Click http://evil.example</p>"},
        {"edited_subject": "Something else"},
        {"edited_recipients": {"to": ["x@elsewhere.com"]}},
    ):
        res, gc = _approve_with_graph(draft_id, edit)
        assert res.status_code == 409, edit
        gc.post.assert_not_called()
    stored = get_draft(draft_id)
    assert stored["status"] == "pending"
    assert stored["params"]["body"] == "Link: aigator://share?d=abc"
    assert stored["params"]["to"] == "a@contoso.com,b@contoso.com"


def test_a_refused_edit_does_not_stop_the_exact_text_from_being_approved_afterwards():
    draft_id = _data()["draft_id"]
    refused, _ = _approve_with_graph(draft_id, {"edited_message": "Changed"})
    assert refused.status_code == 409
    res, gc = _approve_with_graph(draft_id)
    assert res.status_code == 200, res.text
    assert "aigator://share?d=abc" in gc.post.call_args.args[1]["message"]["body"]["content"]


def test_a_failed_send_keeps_the_draft_so_it_can_be_approved_again():
    draft_id = _data()["draft_id"]
    gc = MagicMock()
    gc.post.side_effect = RuntimeError("graph down")
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        failed = _approve(draft_id)
    assert failed.status_code == 500
    assert get_draft(draft_id)["status"] == "pending"
    res, gc = _approve_with_graph(draft_id)
    assert res.status_code == 200, res.text
