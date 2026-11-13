"""A reply card shows the real To and CC, and the user can add or remove people before approving.

Every Graph call here goes to a mock, so none of these tests can send an email.
"""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import app
from skills._drafts import create_draft
from skills.email import tools as email_tools

ME = "me@amd.com"


def _orig(sender, to=(), cc=()):
    def people(addresses):
        return [{"name": a.split("@")[0].title(), "email": a} for a in addresses]

    return {
        "subject": "Prep Session",
        "from_addr": sender,
        "from_name": sender.split("@")[0].title(),
        "to_people": people(to),
        "cc_people": people(cc),
    }


def _emails(people):
    return [p["email"] for p in people]


class TestReplyRecipients:
    def test_plain_reply_goes_to_the_sender_only(self):
        orig = _orig("ann@amd.com", to=[ME, "bob@amd.com"], cc=["cy@amd.com"])
        to, cc = email_tools._reply_recipients(orig, False, ME)
        assert _emails(to) == ["ann@amd.com"]
        assert cc == []

    def test_reply_all_lists_everyone_but_me(self):
        orig = _orig("ann@amd.com", to=[ME, "bob@amd.com"], cc=["cy@amd.com", ME.upper()])
        to, cc = email_tools._reply_recipients(orig, True, ME)
        assert _emails(to) == ["ann@amd.com", "bob@amd.com"]
        assert _emails(cc) == ["cy@amd.com"]

    def test_reply_all_does_not_repeat_a_person_on_both_lines(self):
        orig = _orig("ann@amd.com", to=["bob@amd.com"], cc=["Bob@amd.com", "ann@amd.com"])
        to, cc = email_tools._reply_recipients(orig, True, ME)
        assert _emails(to) == ["ann@amd.com", "bob@amd.com"]
        assert cc == []

    def test_replying_to_my_own_message_goes_to_its_recipients(self):
        orig = _orig(ME, to=["bob@amd.com", "cy@amd.com"], cc=["di@amd.com"])
        to, cc = email_tools._reply_recipients(orig, False, ME)
        assert _emails(to) == ["bob@amd.com", "cy@amd.com"]
        assert cc == []
        to, cc = email_tools._reply_recipients(orig, True, ME)
        assert _emails(to) == ["bob@amd.com", "cy@amd.com"]
        assert _emails(cc) == ["di@amd.com"]

    def test_when_my_address_is_unknown_nobody_is_dropped(self):
        orig = _orig("ann@amd.com", to=[ME])
        to, _ = email_tools._reply_recipients(orig, True, "")
        assert _emails(to) == ["ann@amd.com", ME]


class TestReplyCardShowsRecipients:
    def _draft(self, reply_all):
        orig = _orig("ann@amd.com", to=[ME, "bob@amd.com"], cc=["cy@amd.com"])
        with patch.object(email_tools, "_fetch_original_email_context", return_value=orig), patch.object(
            email_tools, "_my_email_address", return_value=ME
        ):
            return email_tools._tool_reply_email("M1", "Thanks", reply_all=reply_all)["data"]

    def test_reply_all_card_carries_every_recipient(self):
        data = self._draft(True)
        assert data["to"] == "ann@amd.com, bob@amd.com"
        assert data["cc"] == "cy@amd.com"
        assert _emails(data["to_people"]) == ["ann@amd.com", "bob@amd.com"]
        assert _emails(data["cc_people"]) == ["cy@amd.com"]

    def test_plain_reply_card_carries_the_sender_only(self):
        data = self._draft(False)
        assert data["to"] == "ann@amd.com"
        assert data["cc"] == ""


def _approve(client, draft_id, body=None):
    from security import get_csrf_token

    return client.post(
        f"/api/drafts/{draft_id}/approve",
        headers={"X-CSRF-Token": get_csrf_token("testserver")},
        json=body,
    )


def _graph():
    gc = MagicMock()
    gc.get.return_value = {"id": "M1", "body": {"content": "<div>quoted</div>"}}
    gc.post.return_value = {"id": "DRAFT1"}
    return gc


def _reply_patch(gc):
    return gc.patch.call_args.args[1]


def _approve_reply(body):
    did = create_draft("email-reply", {"message_id": "M1", "body": "Thanks", "reply_all": True}, {})
    gc = _graph()
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        r = _approve(TestClient(app), did, body=body)
    return r, gc


class TestApproveAppliesRecipientEdits:
    def test_an_untouched_reply_keeps_the_recipients_outlook_chose(self):
        r, gc = _approve_reply({"edited_message": "Thanks"})
        assert r.status_code == 200, r.text
        assert "toRecipients" not in _reply_patch(gc)
        assert "ccRecipients" not in _reply_patch(gc)

    def test_a_removed_and_an_added_person_reach_the_draft(self):
        r, gc = _approve_reply({"edited_recipients": {"to": ["ann@amd.com", "new@amd.com"], "cc": []}})
        assert r.status_code == 200, r.text
        patched = _reply_patch(gc)
        assert [x["emailAddress"]["address"] for x in patched["toRecipients"]] == ["ann@amd.com", "new@amd.com"]
        assert patched["ccRecipients"] == []
        assert "quoted" in patched["body"]["content"]

    def test_only_the_line_that_changed_is_patched(self):
        r, gc = _approve_reply({"edited_recipients": {"cc": ["cy@amd.com"]}})
        assert r.status_code == 200, r.text
        assert "toRecipients" not in _reply_patch(gc)
        assert _reply_patch(gc)["ccRecipients"][0]["emailAddress"]["address"] == "cy@amd.com"

    def test_bad_edits_are_rejected_before_anything_is_sent(self):
        bad = [
            {"edited_recipients": {"to": []}},
            {"edited_recipients": {"to": ["not-an-address"]}},
            {"edited_recipients": {"to": ["a@amd.com, b@amd.com"]}},
            {"edited_recipients": {"bcc": ["a@amd.com"]}},
            {"edited_recipients": {"to": "a@amd.com"}},
            {"edited_recipients": {"to": ["a@amd.com"], "cc": [f"p{i}@amd.com" for i in range(51)]}},
        ]
        for body in bad:
            r, gc = _approve_reply(body)
            assert r.status_code == 400, (body, r.text)
            assert not gc.post.called, body

    def test_a_person_listed_twice_is_sent_once(self):
        r, gc = _approve_reply({"edited_recipients": {"to": ["ann@amd.com", "ANN@amd.com"]}})
        assert r.status_code == 200, r.text
        assert len(_reply_patch(gc)["toRecipients"]) == 1
