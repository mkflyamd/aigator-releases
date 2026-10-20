import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import app
from skills import _drafts


def setup_function(function):
    _drafts._pending_drafts.clear()


def _post(client, draft_id, action, body=None):
    from security import get_csrf_token

    return client.post(
        f"/api/drafts/{draft_id}/{action}",
        headers={"X-CSRF-Token": get_csrf_token("testserver")},
        json=body,
    )


def _gc():
    gc = MagicMock()
    gc.post.return_value = {"id": "NEWID"}
    gc.get.return_value = {"body": {"content": "<p>quoted</p>"}}
    return gc


def _sent_content(gc):
    call = next(c for c in gc.post.call_args_list if c.args[0] == "/me/sendMail")
    return call.args[1]["message"]["body"]["content"]


def _email_send(**extra):
    params = {"to": "bob@amd.com", "subject": "S", "body": "stale", "body_html": "<p>stale</p>"}
    params.update(extra)
    return _drafts.create_draft("email-send", params, {})


def test_send_with_edited_html_keeps_formatting():
    gc = _gc()
    did = _email_send()
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        r = _post(TestClient(app), did, "approve", {"edited_html": "<p><b>Bold</b> text</p>"})
    assert r.status_code == 200, r.text
    content = _sent_content(gc)
    assert content.startswith("<!DOCTYPE html>")
    assert "<p><b>Bold</b> text</p>" in content
    assert "stale" not in content


def test_send_sanitizes_edited_html():
    gc = _gc()
    did = _email_send()
    edited = '<p onclick="x()">Hi</p><script>alert(1)</script>'
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        r = _post(TestClient(app), did, "approve", {"edited_html": edited})
    assert r.status_code == 200, r.text
    content = _sent_content(gc)
    assert "<p>Hi</p>" in content
    assert "onclick" not in content and "script" not in content


def test_send_plain_edited_message_keeps_line_breaks():
    gc = _gc()
    did = _email_send()
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        r = _post(TestClient(app), did, "approve", {"edited_message": "Line one\nLine two"})
    assert r.status_code == 200, r.text
    content = _sent_content(gc)
    assert "<p>Line one<br>Line two</p>" in content
    assert "stale" not in content


def test_send_without_edit_uses_stored_body_html():
    gc = _gc()
    did = _email_send(body="plain", body_html="<p><i>kept</i></p>")
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        r = _post(TestClient(app), did, "approve")
    assert r.status_code == 200, r.text
    assert "<p><i>kept</i></p>" in _sent_content(gc)


def test_send_cleared_editor_does_not_resurrect_stale_text():
    gc = _gc()
    did = _email_send()
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        r = _post(TestClient(app), did, "approve", {"edited_html": ""})
    assert r.status_code == 200, r.text
    content = _sent_content(gc)
    assert "<body></body>" in content
    assert "stale" not in content


def test_reply_approve_uses_edited_html():
    gc = _gc()
    did = _drafts.create_draft(
        "email-reply",
        {"message_id": "AAMk1", "body": "old", "body_html": "<p>old</p>", "reply_all": False},
        {},
    )
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        r = _post(TestClient(app), did, "approve", {"edited_html": "<p><b>Hi</b></p>"})
    assert r.status_code == 200, r.text
    assert gc.patch.call_args.args[1]["body"]["content"] == "<p><b>Hi</b></p><p>quoted</p>"


def test_forward_approve_uses_edited_html():
    gc = _gc()
    did = _drafts.create_draft(
        "email-forward",
        {"message_id": "AAMk1", "to": "bob@amd.com", "comment": "old", "body_html": "<p>old</p>"},
        {},
    )
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        r = _post(TestClient(app), did, "approve", {"edited_html": "<p><u>FYI</u></p>"})
    assert r.status_code == 200, r.text
    assert gc.patch.call_args.args[1]["body"]["content"] == "<p><u>FYI</u></p><p>quoted</p>"


def test_open_in_outlook_email_send_posts_bare_fragment():
    gc = _gc()
    did = _email_send()
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        r = _post(TestClient(app), did, "open-in-outlook", {"edited_html": "<p><b>Bold</b> text</p>"})
    assert r.status_code == 200, r.text
    created = next(c for c in gc.post.call_args_list if c.args[0] == "/me/messages")
    assert created.args[1]["body"]["content"] == "<p><b>Bold</b> text</p>"


def test_open_in_outlook_reply_uses_edited_html():
    gc = _gc()
    did = _drafts.create_draft(
        "email-reply",
        {"message_id": "AAMk1", "body": "old", "body_html": "<p>old</p>", "reply_all": False},
        {},
    )
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        r = _post(TestClient(app), did, "open-in-outlook", {"edited_html": "<p><b>Hi</b></p>"})
    assert r.status_code == 200, r.text
    assert gc.patch.call_args.args[1]["body"]["content"] == "<p><b>Hi</b></p><p>quoted</p>"
