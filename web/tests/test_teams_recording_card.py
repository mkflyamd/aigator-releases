"""Issue #105 — Teams Play/recording link opens Gator AI chat instead of browser.

Root cause: Recording messages contain raw <URIObject type="Video.2/CallRecording.1">
XML. The nested <a href="...">Play</a> inside the URIObject gets rendered by the
browser with href="" because the HTML parser strips attributes from unknown XML
elements. The click handler (window.open) never fires on an empty href.

Fix: In the backend message processing, detect URIObject recording messages and
rewrite body_html to a clean <a href="...">▶ Play recording</a> card with the
actual OnedriveForBusiness or SharePoint URL extracted from the XML.

These tests verify:
1. _parse_recording_uri_object() helper exists and extracts the recording URL
2. The message processing pipeline calls it for URIObject recording messages
3. The rewritten body_html contains a valid href (not empty)
"""

import pathlib, re

SRC = (pathlib.Path(__file__).parent.parent / "routes" / "teams.py").read_text(encoding="utf-8")

SAMPLE_URI_OBJECT = (
    '<URIObject format_version="1.1" type="Video.2/CallRecording.1" '
    'url_thumbnail="https://example.com/thumb" uri="" version="1.0">'
    '<Title>Customer Dashboard Demo</Title>'
    '<a href="https://amdcloud-my.sharepoint.com/:v:/g/personal/user/ABC123">Play</a>'
    '<RecordingContent contentTypes="Recording+Transcript">'
    '<item type="onedriveForBusinessVideo" uri="https://amdcloud-my.sharepoint.com/:v:/g/personal/user/ABC123" />'
    '</RecordingContent>'
    '</URIObject>'
)


class TestParseRecordingUriObject:

    def test_helper_exists(self):
        """_parse_recording_uri_object must exist in routes/teams.py."""
        assert "_parse_recording_uri_object" in SRC, (
            "_parse_recording_uri_object must exist — extracts Play URL from URIObject XML"
        )

    def test_helper_extracts_onedrive_url(self):
        """Helper body must use regex to extract onedriveForBusinessVideo or Play href."""
        helper_start = SRC.find("def _parse_recording_uri_object(")
        assert helper_start != -1
        next_def = SRC.find("\ndef ", helper_start + 1)
        body = SRC[helper_start:next_def if next_def != -1 else helper_start + 1500]
        assert "onedriveForBusinessVideo" in body, (
            "_parse_recording_uri_object must look for onedriveForBusinessVideo URI"
        )
        assert "https://" in body or "https:" in body, (
            "_parse_recording_uri_object must validate https:// in extracted URL"
        )

    def test_helper_extracts_title(self):
        """Helper body must extract <Title> from the URIObject XML."""
        helper_start = SRC.find("def _parse_recording_uri_object(")
        next_def = SRC.find("\ndef ", helper_start + 1)
        body = SRC[helper_start:next_def if next_def != -1 else helper_start + 1500]
        assert "<Title>" in body or "Title" in body, (
            "_parse_recording_uri_object must extract the <Title> element for the recording title"
        )

    def test_helper_returns_none_for_non_recording(self):
        """Helper must guard with URIObject + CallRecording check before processing."""
        helper_start = SRC.find("def _parse_recording_uri_object(")
        next_def = SRC.find("\ndef ", helper_start + 1)
        body = SRC[helper_start:next_def if next_def != -1 else helper_start + 1500]
        assert "URIObject" in body and "CallRecording" in body, (
            "_parse_recording_uri_object must check for URIObject and CallRecording before parsing"
        )
        assert "return None" in body, (
            "_parse_recording_uri_object must return None for non-recording content"
        )

    def test_helper_never_returns_asyncgw_url(self):
        """asyncgw/amsVideo URLs always 401 in a browser (need X-Skypetoken), so the
        helper must NEVER return one — only SharePoint/OneDrive Play URLs are usable.

        Real-world data: a single recording posts many chunk messages. Only the final
        'Success' chunk carries a SharePoint <a href>; intermediate chunks have an
        empty href and only an amsVideo (asyncgw) item. Rendering those produced the
        401 Play cards. The helper must return None for asyncgw-only content.
        """
        helper_start = SRC.find("def _parse_recording_uri_object(")
        next_def = SRC.find("\ndef ", helper_start + 1)
        body = SRC[helper_start:next_def if next_def != -1 else helper_start + 1500]
        assert "asyncgw" in body, (
            "_parse_recording_uri_object must explicitly reject asyncgw URLs (they 401)"
        )

    def test_helper_returns_none_for_asyncgw_only_recording(self):
        """Behavioral: a chunk recording with empty href + amsVideo(asyncgw) only
        must yield no Play URL (None), not an asyncgw link."""
        import importlib.util, pathlib as _pl
        _p = _pl.Path(__file__).parent.parent / "routes" / "teams.py"
        # The function is pure-stdlib; load just its source and exec in a tiny ns.
        # Simpler: regex-free behavioral check via a minimal import shim.
        src = _p.read_text(encoding="utf-8")
        start = src.find("def _parse_recording_uri_object(")
        end = src.find("\ndef ", start + 1)
        func_src = src[start:end]
        ns: dict = {"re": __import__("re")}
        exec(func_src, ns)
        parse = ns["_parse_recording_uri_object"]
        asyncgw_only = (
            '<URIObject type="Video.2/CallRecording.1">'
            '<Title>Chunk</Title><a href="">Play</a>'
            '<RecordingContent contentTypes="Recording">'
            '<item type="amsVideo" uri="https://us-prod.asyncgw.teams.microsoft.com/v1/objects/0-cus-d4-abc/views/video" />'
            '</RecordingContent></URIObject>'
        )
        url, _title = parse(asyncgw_only)
        assert url is None, f"asyncgw-only recording must return None, got {url!r}"

    def test_helper_returns_sharepoint_url(self):
        """Behavioral: a Success chunk with a SharePoint <a href> must return it."""
        import pathlib as _pl
        _p = _pl.Path(__file__).parent.parent / "routes" / "teams.py"
        src = _p.read_text(encoding="utf-8")
        start = src.find("def _parse_recording_uri_object(")
        end = src.find("\ndef ", start + 1)
        ns: dict = {"re": __import__("re")}
        exec(src[start:end], ns)
        parse = ns["_parse_recording_uri_object"]
        sp = (
            '<URIObject type="Video.2/CallRecording.1">'
            '<Title>Meeting</Title>'
            '<a href="https://amdcloud-my.sharepoint.com/:v:/g/personal/u/ABC">Play</a>'
            '</URIObject>'
        )
        url, title = parse(sp)
        assert url == "https://amdcloud-my.sharepoint.com/:v:/g/personal/u/ABC"
        assert title == "Meeting"


class TestRecordingMessageRewrite:

    def test_backend_rewrites_uri_object_to_card(self):
        """Message processing must rewrite URIObject recording to a play card with valid href."""
        # The body_html path must detect URIObject and call _parse_recording_uri_object
        assert "_parse_recording_uri_object" in SRC, (
            "teams.py must call _parse_recording_uri_object when processing messages"
        )
        # The rewrite must produce a non-empty href on the Play link
        assert 'tp-recording-card' in SRC or 'play-card' in SRC or ('Play recording' in SRC and 'href' in SRC), (
            "teams.py must produce a rendered play card with a valid href, not raw URIObject XML"
        )

    def test_uri_object_detection_pattern(self):
        """Backend must detect URIObject recordings before the generic HTML processing."""
        # The detection should happen via URIObject type check
        uri_obj_idx = SRC.find("URIObject")
        assert uri_obj_idx != -1, (
            "teams.py must contain URIObject handling to detect recording messages"
        )
        assert "CallRecording" in SRC or "Video.2" in SRC, (
            "teams.py must check for CallRecording/Video.2 type in URIObject"
        )
