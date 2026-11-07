"""A new-email draft card shows its To and CC as editable people, and the user's edits are what gets sent.

Every Graph call here goes to a mock, so none of these tests can send an email.
"""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import app
from skills._drafts import create_draft
from skills.email import tools as email_tools


def _addresses(recipients):
    return [r["emailAddress"]["address"] for r in recipients]


def _post(client, draft_id, action, body=None):
    from security import get_csrf_token

    return client.post(
        f"/api/drafts/{draft_id}/{action}",
        headers={"X-CSRF-Token": get_csrf_token("testserver")},
        json=body,
    )


def _compose(**kw):
    params = {"to": "ann@amd.com, bob@amd.com", "subject": "Update", "body": "Hello", "cc": "cy@amd.com", "bcc": "ed@amd.com"}
    params.update(kw)
    return create_draft("email-send", params, {})


def _send(body):
    gc = MagicMock()
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        r = _post(TestClient(app), _compose(), "approve", body)
    return r, gc


class TestComposeCardCarriesPeople:
    def _data(self, **kw):
        args = {"to": "ann@amd.com, bob@amd.com", "subject": "Update", "body": "Hi", "cc": "cy@amd.com"}
        args.update(kw)
        return email_tools._tool_email_open_compose(**args)["data"]

    def test_every_to_and_cc_address_is_a_person(self):
        data = self._data()
        assert [p["email"] for p in data["to_people"]] == ["ann@amd.com", "bob@amd.com"]
        assert [p["email"] for p in data["cc_people"]] == ["cy@amd.com"]

    def test_names_are_used_when_they_line_up_with_the_addresses(self):
        data = self._data(to_names="Ann Lee, Bob Ray")
        assert [p["name"] for p in data["to_people"]] == ["Ann Lee", "Bob Ray"]

    def test_names_that_do_not_line_up_are_ignored(self):
        data = self._data(to_names="Ann Lee")
        assert [p["name"] for p in data["to_people"]] == ["", ""]

    def test_no_cc_is_an_empty_list(self):
        assert self._data(cc="")["cc_people"] == []


class TestApproveSendsEditedRecipients:
    def test_an_untouched_card_sends_to_everyone_it_listed(self):
        r, gc = _send({"edited_message": "Hello"})
        assert r.status_code == 200, r.text
        msg = gc.post.call_args.args[1]["message"]
        assert _addresses(msg["toRecipients"]) == ["ann@amd.com", "bob@amd.com"]
        assert _addresses(msg["ccRecipients"]) == ["cy@amd.com"]
        assert _addresses(msg["bccRecipients"]) == ["ed@amd.com"]

    def test_a_removed_and_an_added_person_are_what_gets_sent(self):
        r, gc = _send({"edited_recipients": {"to": ["ann@amd.com", "new@amd.com"], "cc": []}})
        assert r.status_code == 200, r.text
        msg = gc.post.call_args.args[1]["message"]
        assert _addresses(msg["toRecipients"]) == ["ann@amd.com", "new@amd.com"]
        assert "ccRecipients" not in msg
        assert _addresses(msg["bccRecipients"]) == ["ed@amd.com"], "Bcc is not editable and is left alone"

    def test_only_the_line_that_changed_is_replaced(self):
        r, gc = _send({"edited_recipients": {"cc": ["di@amd.com"]}})
        assert r.status_code == 200, r.text
        msg = gc.post.call_args.args[1]["message"]
        assert _addresses(msg["toRecipients"]) == ["ann@amd.com", "bob@amd.com"]
        assert _addresses(msg["ccRecipients"]) == ["di@amd.com"]

    def test_bad_edits_are_rejected_before_anything_is_sent(self):
        bad = [
            {"edited_recipients": {"to": []}},
            {"edited_recipients": {"to": ["not-an-address"]}},
            {"edited_recipients": {"bcc": ["a@amd.com"]}},
            {"edited_recipients": {"to": "a@amd.com"}},
        ]
        for body in bad:
            r, gc = _send(body)
            assert r.status_code == 400, (body, r.text)
            assert not gc.post.called, body


class TestOpenInOutlookKeepsEditedRecipients:
    def test_the_outlook_draft_has_the_edited_people(self):
        gc = MagicMock()
        gc.post.return_value = {"id": "DRAFT1", "webLink": "https://outlook.office.com/mail/x"}
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = _post(
                TestClient(app),
                _compose(),
                "open-in-outlook",
                {"edited_recipients": {"to": ["ann@amd.com"], "cc": ["di@amd.com"]}},
            )
        assert r.status_code == 200, r.text
        path, msg = gc.post.call_args_list[0].args
        assert path == "/me/messages"
        assert _addresses(msg["toRecipients"]) == ["ann@amd.com"]
        assert _addresses(msg["ccRecipients"]) == ["di@amd.com"]


class TestEditedSubject:
    def test_the_edited_subject_is_what_gets_sent(self):
        r, gc = _send({"edited_subject": "  Updated: recordings  "})
        assert r.status_code == 200, r.text
        assert gc.post.call_args.args[1]["message"]["subject"] == "Updated: recordings"

    def test_an_untouched_card_keeps_its_subject(self):
        r, gc = _send({"edited_message": "Hello"})
        assert gc.post.call_args.args[1]["message"]["subject"] == "Update"

    def test_bad_subjects_are_rejected_before_anything_is_sent(self):
        for subject in ["", "   ", "two\nlines", "x" * 256, 5]:
            r, gc = _send({"edited_subject": subject})
            assert r.status_code == 400, (subject, r.text)
            assert not gc.post.called, subject

    def test_the_outlook_draft_has_the_edited_subject(self):
        gc = MagicMock()
        gc.post.return_value = {"id": "DRAFT1", "webLink": "https://outlook.office.com/mail/x"}
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = _post(TestClient(app), _compose(), "open-in-outlook", {"edited_subject": "New subject"})
        assert r.status_code == 200, r.text
        assert gc.post.call_args_list[0].args[1]["subject"] == "New subject"
