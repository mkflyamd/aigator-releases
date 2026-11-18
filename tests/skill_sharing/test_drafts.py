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
