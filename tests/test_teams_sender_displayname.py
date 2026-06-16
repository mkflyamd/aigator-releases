"""Issue #56: Teams messages sent via Gator showed the sender as a raw AAD
object id (GUID) instead of the display name.

Root cause: the Skype chatsvc message body omitted `imdisplayname`, so clients
fell back to the sender's MRI/object id. The fix builds every Skype send body
through a shared helper that sets `imdisplayname` to the current user's name.
"""
import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from routes.teams import _skype_send_body


def test_skype_send_body_includes_imdisplayname():
    body = _skype_send_body("<div>hi</div>", "RichText/Html", "Smith, James")
    assert body["imdisplayname"] == "Smith, James"
    assert body["content"] == "<div>hi</div>"
    assert body["messagetype"] == "RichText/Html"
    assert body["contenttype"] == "text"


def test_skype_send_body_omits_imdisplayname_when_name_blank():
    body = _skype_send_body("hi", "Text", "")
    assert "imdisplayname" not in body
    assert body["content"] == "hi"
    assert body["messagetype"] == "Text"
