from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import app
from security import get_csrf_token
from skills._drafts import get_draft
from skills._sharing import drafts
from skills.email.tools import _tool_email_open_compose

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


def _build_note(**kwargs):
    with patch("skills.email.tools._tool_email_open_compose", wraps=_tool_email_open_compose) as compose:
        out = drafts.build(skill_id="s", people=PEOPLE, **kwargs)
    return compose.call_args.kwargs, out


def test_the_html_message_goes_to_the_draft_body_html():
    kwargs, _ = _build_note(message="text", message_html="<p>html</p>")
    assert kwargs["body_html"] == "<p>html</p>"


def test_the_note_goes_in_front_of_the_message_in_both_forms():
    kwargs, _ = _build_note(message="text", message_html="<p>html</p>", note="Hi, here you go.")
    assert kwargs["body"] == "Hi, here you go.\n\ntext"
    assert kwargs["body_html"] == "<p>Hi, here you go.</p><p>html</p>"


def test_the_note_is_escaped_in_the_html_and_keeps_its_line_breaks():
    kwargs, _ = _build_note(message="text", message_html="<p>html</p>", note="<b>Hi</b> & bye\nsecond line")
    assert kwargs["body_html"] == "<p>&lt;b&gt;Hi&lt;/b&gt; &amp; bye<br>second line</p><p>html</p>"


def test_a_blank_note_changes_nothing():
    kwargs, _ = _build_note(message="text", message_html="<p>html</p>", note="   ")
    assert kwargs["body"] == "text"
    assert kwargs["body_html"] == "<p>html</p>"


def test_a_note_without_an_html_message_leaves_the_html_to_be_made_from_the_text():
    kwargs, _ = _build_note(message="text", note="Hi")
    assert kwargs["body"] == "Hi\n\ntext"
    assert kwargs["body_html"] == ""


def test_a_drafted_note_never_sends_anything():
    with patch("routes.drafts.approve_draft") as approve:
        out = drafts.build(skill_id="s", people=PEOPLE, message="text", note="Hi")
    approve.assert_not_called()
    assert out["drafts"][0]["_draft"] == "email-send"
    assert out["drafts"][0]["data"]["body"] == "Hi\n\ntext"
