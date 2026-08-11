"""Issue #149 — Teams messages with received/attached files render blank.

Root cause: Skype/chatsvc (the primary Teams read path) never puts file-share
info in the message content/HTML at all. It lives entirely in a separate,
double-JSON-encoded field: message.properties.files — a list of File objects
carrying fileName + fileInfo.shareUrl/fileUrl. A file share with no typed
caption has content == "", so the message rendered as a completely empty
bubble: _normalize_skype_messages() hardcoded "attachments": [] and never
read properties.files.

Verified against real captured Skype chatsvc payloads (see PR description):
  properties.files (JSON string) == [{
    "itemid": "...", "fileName": "report.zst", "fileType": "zst",
    "fileInfo": {"fileUrl": "https://.../report.zst",
                 "shareUrl": "https://.../:u:/g/personal/.../ABC123",
                 "siteUrl": "https://...", "shareId": "..."},
    "@type": "http://schema.skype.com/File", ...
  }]

Fix: _extract_skype_file_attachments() parses properties.files (decoding the
JSON string when needed) into the same attachment shape the frontend already
expects from the Graph fallback path: {id, name, content_type, content_url,
thumbnail_url}. _normalize_skype_messages() and the Skype channel-messages
path now populate "attachments" from it instead of a hardcoded [].
"""

import json
import pathlib
import re

SRC = (pathlib.Path(__file__).parent.parent / "routes" / "teams.py").read_text(encoding="utf-8")


def _extract_def(name: str) -> str:
    start = SRC.find(f"def {name}(")
    assert start != -1, f"{name} not found in routes/teams.py"
    nxt = SRC.find("\ndef ", start + 1)
    return SRC[start: nxt if nxt != -1 else start + 3000]


def _build_ns() -> dict:
    import urllib.parse as _up
    ns: dict = {"re": re, "json": json, "urllib": __import__("urllib")}
    ns["urllib"].parse = _up
    exec(_extract_def("_extract_forward_context"), ns)
    exec(_extract_def("_extract_skype_file_attachments"), ns)
    exec(_extract_def("_map_graph_attachments"), ns)
    return ns


# A genericized (non-real) but structurally identical fixture, matching the
# real Skype properties.files shape captured for this issue.
SAMPLE_FILE_ITEM = {
    "itemid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "fileName": "quarterly-report.pptx",
    "fileType": "pptx",
    "fileInfo": {
        "itemId": None,
        "fileUrl": "https://contoso-my.sharepoint.com/personal/user_contoso_com/Documents/Microsoft%20Teams%20Chat%20Files/quarterly-report.pptx",
        "siteUrl": "https://contoso-my.sharepoint.com/personal/user_contoso_com/",
        "serverRelativeUrl": "",
        "shareUrl": "https://contoso-my.sharepoint.com/:p:/g/personal/user_contoso_com/EXAMPLE123",
        "shareId": "11111111-2222-3333-4444-555555555555",
    },
    "@type": "http://schema.skype.com/File",
    "version": 2,
    "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "objectUrl": "https://contoso-my.sharepoint.com/personal/user_contoso_com/Documents/Microsoft%20Teams%20Chat%20Files/quarterly-report.pptx",
    "type": "pptx",
    "title": "quarterly-report.pptx",
    "state": "active",
}


class TestExtractSkypeFileAttachments:

    def test_helper_exists(self):
        assert "_extract_skype_file_attachments" in SRC

    def test_prefers_share_url_over_file_url(self):
        ns = _build_ns()
        fn = ns["_extract_skype_file_attachments"]
        out = fn({"files": [SAMPLE_FILE_ITEM]})
        assert len(out) == 1
        assert out[0]["content_url"] == SAMPLE_FILE_ITEM["fileInfo"]["shareUrl"]
        assert out[0]["name"] == "quarterly-report.pptx"
        assert out[0]["content_type"] == "pptx"
        assert out[0]["id"] == SAMPLE_FILE_ITEM["itemid"]

    def test_handles_double_json_encoded_files_property(self):
        """Real Skype payloads carry properties.files as a JSON *string*, not a
        pre-parsed list — this is the exact shape captured from a live chat."""
        ns = _build_ns()
        fn = ns["_extract_skype_file_attachments"]
        props = {"files": json.dumps([SAMPLE_FILE_ITEM])}
        out = fn(props)
        assert len(out) == 1
        assert out[0]["name"] == "quarterly-report.pptx"

    def test_falls_back_to_file_url_when_share_url_missing(self):
        ns = _build_ns()
        fn = ns["_extract_skype_file_attachments"]
        item = json.loads(json.dumps(SAMPLE_FILE_ITEM))
        del item["fileInfo"]["shareUrl"]
        out = fn({"files": [item]})
        assert out[0]["content_url"] == item["fileInfo"]["fileUrl"]

    def test_returns_empty_list_for_no_files(self):
        ns = _build_ns()
        fn = ns["_extract_skype_file_attachments"]
        assert fn({}) == []
        assert fn({"files": []}) == []
        assert fn({"files": None}) == []

    def test_skips_items_without_a_name(self):
        ns = _build_ns()
        fn = ns["_extract_skype_file_attachments"]
        item = json.loads(json.dumps(SAMPLE_FILE_ITEM))
        del item["fileName"]
        del item["title"]
        assert fn({"files": [item]}) == []

    def test_skips_items_without_any_usable_url(self):
        ns = _build_ns()
        fn = ns["_extract_skype_file_attachments"]
        item = {"fileName": "no-url.txt", "fileInfo": {}}
        assert fn({"files": [item]}) == []

    def test_handles_malformed_json_gracefully(self):
        ns = _build_ns()
        fn = ns["_extract_skype_file_attachments"]
        assert fn({"files": "{not valid json"}) == []


class TestMapGraphAttachments:

    def test_helper_exists(self):
        assert "_map_graph_attachments" in SRC

    def test_maps_graph_shape(self):
        ns = _build_ns()
        fn = ns["_map_graph_attachments"]
        out = fn([{"id": "1", "name": "a.pdf", "contentType": "reference",
                    "contentUrl": "https://example/a.pdf", "thumbnailUrl": ""}])
        assert out == [{"id": "1", "name": "a.pdf", "content_type": "reference",
                         "content_url": "https://example/a.pdf", "thumbnail_url": ""}]

    def test_skips_unnamed_attachments(self):
        ns = _build_ns()
        fn = ns["_map_graph_attachments"]
        assert fn([{"id": "1", "contentUrl": "https://example/a.pdf"}]) == []

    def test_handles_none(self):
        ns = _build_ns()
        fn = ns["_map_graph_attachments"]
        assert fn(None) == []


class TestNormalizeSkypeMessagesSurfacesAttachments:

    def test_no_longer_hardcodes_empty_attachments_in_normalize_skype_messages(self):
        body = _extract_def("_normalize_skype_messages")
        # The systemEvent branch legitimately hardcodes "attachments": [] (system
        # events can't carry files) — only assert the real *message* append site
        # (identified by "reactions": reactions immediately preceding it) now
        # calls the helper instead of hardcoding an empty list.
        assert '"reactions": reactions,\n            "attachments": _extract_skype_file_attachments(' in body, (
            "_normalize_skype_messages's message-append site must call "
            "_extract_skype_file_attachments instead of hardcoding attachments "
            "to an empty list (#149)"
        )

    def test_file_only_message_with_empty_body_still_surfaces_attachment(self):
        """Behavioral: a caption-less file share (content == '') is exactly the
        case that rendered as a totally blank bubble before the fix."""
        ns = _build_ns()
        exec(_extract_def("_normalize_skype_messages"), ns)
        normalize = ns["_normalize_skype_messages"]

        raw_msgs = [{
            "id": "1784762458324",
            "from": "https://x/contacts/8:orgid:aaaa",
            "from_mri": "8:orgid:aaaa",
            "sender_name": "Test Sender",
            "content": "",
            "content_html": "",
            "time": "2026-07-22T23:20:58.3240000Z",
            "raw_properties": {"files": json.dumps([SAMPLE_FILE_ITEM])},
            "edit_time": "",
            "emotions_raw": [],
            "mention_map": {},
        }]
        out = normalize(raw_msgs, my_mri="", my_name="")
        assert len(out) == 1
        msg = out[0]
        assert msg["body"] == ""
        assert msg["body_html"] == ""
        assert len(msg["attachments"]) == 1
        assert msg["attachments"][0]["name"] == "quarterly-report.pptx"
        assert msg["attachments"][0]["content_url"] == SAMPLE_FILE_ITEM["fileInfo"]["shareUrl"]


class TestChannelSkypePathSurfacesAttachments:

    def test_channel_parent_and_reply_use_the_helper(self):
        # tp_channel_messages is large; slice from its def to the next top-level def
        start = SRC.find("async def tp_channel_messages(")
        assert start != -1
        nxt = SRC.find("\n@router.", start + 1)
        body = SRC[start: nxt if nxt != -1 else start + 6000]
        occurrences = body.count("_extract_skype_file_attachments(")
        assert occurrences >= 2, (
            "tp_channel_messages must call _extract_skype_file_attachments for "
            "both the thread-parent and reply message branches (#149), found "
            f"{occurrences} call(s)"
        )
        # Graph fallback within the same endpoint must also map attachments.
        assert body.count("_map_graph_attachments(") >= 2, (
            "tp_channel_messages Graph fallback must map attachments for both "
            "parent and reply messages via _map_graph_attachments"
        )
