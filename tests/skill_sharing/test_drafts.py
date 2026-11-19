from unittest.mock import patch

from skills._sharing import drafts

PEOPLE = [{"name": "Ann Lee", "email": "A@Contoso.com"}, {"name": "Bo Chen", "email": "b@contoso.com"}]


def _build(people=PEOPLE):
    return drafts.build(skill_id="my-skill", people=people, message="Link: aigator://share?d=abc")


def test_makes_one_email_draft_for_everyone():
    with patch("skills.email.tools._tool_email_open_compose", return_value={"_draft": "email-send"}) as compose:
        out = _build()
    compose.assert_called_once()
    kwargs = compose.call_args.kwargs
    assert kwargs["to"] == "a@contoso.com,b@contoso.com"
    assert kwargs["to_names"] == "Ann Lee,Bo Chen"
    assert "my-skill" in kwargs["subject"]
    assert kwargs["body"] == "Link: aigator://share?d=abc"
    assert out == {"drafts": [{"_draft": "email-send"}], "unmatched": []}


def test_names_are_left_out_unless_everyone_has_one():
    with patch("skills.email.tools._tool_email_open_compose", return_value={}) as compose:
        _build([{"name": "Ann Lee", "email": "a@contoso.com"}, {"email": "b@contoso.com"}])
    assert compose.call_args.kwargs["to_names"] == ""


def test_a_comma_in_a_name_cannot_shift_the_names_onto_other_addresses():
    with patch("skills.email.tools._tool_email_open_compose", return_value={}) as compose:
        _build([{"name": "Lee, Ann", "email": "a@contoso.com"}, {"name": "Bo", "email": "b@contoso.com"}])
    assert compose.call_args.kwargs["to_names"] == "Lee Ann,Bo"


def test_the_html_message_goes_to_the_draft_body_html():
    with patch("skills.email.tools._tool_email_open_compose", return_value={}) as compose:
        drafts.build(skill_id="s", people=PEOPLE, message="text", message_html="<p>html</p>")
    assert compose.call_args.kwargs["body_html"] == "<p>html</p>"


def test_the_note_goes_in_front_of_the_message_in_both_forms():
    with patch("skills.email.tools._tool_email_open_compose", return_value={}) as compose:
        drafts.build(skill_id="s", people=PEOPLE, message="text", message_html="<p>html</p>", note="Hi, here you go.")
    assert compose.call_args.kwargs["body"] == "Hi, here you go.\n\ntext"
    assert compose.call_args.kwargs["body_html"] == "<p>Hi, here you go.</p><p>html</p>"


def test_the_note_is_escaped_in_the_html_and_keeps_its_line_breaks():
    with patch("skills.email.tools._tool_email_open_compose", return_value={}) as compose:
        drafts.build(skill_id="s", people=PEOPLE, message="text", message_html="<p>html</p>", note="<b>Hi</b> & bye\nsecond line")
    assert compose.call_args.kwargs["body_html"] == "<p>&lt;b&gt;Hi&lt;/b&gt; &amp; bye<br>second line</p><p>html</p>"


def test_a_blank_note_changes_nothing():
    with patch("skills.email.tools._tool_email_open_compose", return_value={}) as compose:
        drafts.build(skill_id="s", people=PEOPLE, message="text", message_html="<p>html</p>", note="   ")
    assert compose.call_args.kwargs["body"] == "text"
    assert compose.call_args.kwargs["body_html"] == "<p>html</p>"


def test_a_note_without_an_html_message_leaves_the_html_to_be_made_from_the_text():
    with patch("skills.email.tools._tool_email_open_compose", return_value={}) as compose:
        drafts.build(skill_id="s", people=PEOPLE, message="text", note="Hi")
    assert compose.call_args.kwargs["body"] == "Hi\n\ntext"
    assert compose.call_args.kwargs["body_html"] == ""


def test_a_drafted_note_never_sends_anything():
    with patch("routes.drafts.approve_draft") as approve:
        out = drafts.build(skill_id="s", people=PEOPLE, message="text", note="Hi")
    approve.assert_not_called()
    assert out["drafts"][0]["_draft"] == "email-send"
    assert out["drafts"][0]["data"]["body"] == "Hi\n\ntext"
