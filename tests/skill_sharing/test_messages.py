import base64
import json

import pytest

from skills._sharing import messages
from skills._sharing.errors import ShareError

FOLDER = {"drive_id": "b!abc", "folder_id": "01XYZ", "web_url": "https://onedrive.example/f", "name": "weekly-report"}


def _link_with(payload: bytes) -> str:
    return "aigator://share?d=" + base64.urlsafe_b64encode(payload).decode().rstrip("=")


def test_link_round_trips():
    link = messages.make_share_link(FOLDER)
    assert link.startswith("aigator://share?d=")
    assert "=" not in link.split("?d=", 1)[1]
    assert messages.parse_share_link(link) == {"drive_id": "b!abc", "folder_id": "01XYZ"}


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://share?d=abc",
        "aigator://other?d=abc",
        "aigator://share",
        "aigator://share?d=",
        "aigator://share?d=%%%",
        "aigator://share?d=abc&d=def",
        "aigator://share?x=1",
    ],
)
def test_bad_links_are_refused(url):
    with pytest.raises(ShareError) as err:
        messages.parse_share_link(url)
    assert err.value.code == "invalid_link"


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b"[]",
        json.dumps({"v": 2, "drive_id": "d", "folder_id": "f"}).encode(),
        json.dumps({"v": 1, "drive_id": "d"}).encode(),
        json.dumps({"v": 1, "drive_id": "d", "folder_id": 5}).encode(),
        json.dumps({"v": 1, "drive_id": "d", "folder_id": "f", "extra": "x"}).encode(),
        json.dumps({"v": 1, "drive_id": "", "folder_id": "f"}).encode(),
        json.dumps({"v": 1, "drive_id": "d" * 600, "folder_id": "f"}).encode(),
    ],
)
def test_bad_payloads_are_refused(payload):
    with pytest.raises(ShareError) as err:
        messages.parse_share_link(_link_with(payload))
    assert err.value.code == "invalid_link"


def test_oversized_links_are_refused():
    with pytest.raises(ShareError):
        messages.parse_share_link("aigator://share?d=" + "A" * 5000)


def test_message_has_title_author_link_and_fallback():
    text = messages.share_message(
        "Weekly Report", "Mayuresh Kulkarni", "Summarise the week", "aigator://share?d=abc", "https://onedrive.example/f"
    )
    assert "Mayuresh Kulkarni" in text
    assert '"Weekly Report"' in text
    assert "Summarise the week" in text
    assert "aigator://share?d=abc" in text
    assert "https://onedrive.example/f" in text
    assert "review" in text.lower()


def test_message_without_description_or_web_url_has_no_blank_gaps():
    text = messages.share_message("Weekly Report", "Mayuresh Kulkarni", "", "aigator://share?d=abc")
    assert "\n\n\n" not in text
    assert "OneDrive" not in text


def test_message_flattens_whitespace_in_user_text():
    text = messages.share_message("Weekly\nReport", "May\r\nur", "line one\nline two", "aigator://share?d=abc")
    assert '"Weekly Report"' in text
    assert "line one line two" in text
