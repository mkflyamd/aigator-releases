"""Issue #161: File-routing primitives — Teams attachment resolution and
cross-drive file move/copy.

Tests verify:
  - TOOL_DEFS exports the five expected tool names
  - TOOL_HANDLERS maps each tool to a callable
  - Tool input_schema have the required fields documented in the issue
  - drive_id parameter exists on read_onedrive_file and list_onedrive_files
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import importlib.util


def _load_tools():
    spec = importlib.util.spec_from_file_location(
        "onedrive_tools",
        str(pathlib.Path(__file__).parent.parent / "web" / "skills" / "onedrive" / "tools.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_new_tool_defs_present():
    mod = _load_tools()
    names = {t["name"] for t in mod.TOOL_DEFS}
    assert "resolve_teams_attachment" in names, "resolve_teams_attachment tool missing"
    assert "move_onedrive_file" in names, "move_onedrive_file tool missing"
    assert "copy_onedrive_file" in names, "copy_onedrive_file tool missing"
    assert "get_onedrive_item" in names, "get_onedrive_item tool missing"


def test_new_tool_handlers_callable():
    mod = _load_tools()
    for name in ("resolve_teams_attachment", "move_onedrive_file",
                 "copy_onedrive_file", "get_onedrive_item"):
        assert name in mod.TOOL_HANDLERS, f"TOOL_HANDLERS missing {name}"
        assert callable(mod.TOOL_HANDLERS[name]), f"{name} handler not callable"


def test_resolve_teams_attachment_schema():
    mod = _load_tools()
    tool = next(t for t in mod.TOOL_DEFS if t["name"] == "resolve_teams_attachment")
    props = tool["input_schema"]["properties"]
    required = tool["input_schema"].get("required", [])
    assert "chat_id" in props
    assert "message_id" in props
    assert "chat_id" in required
    assert "message_id" in required


def test_move_onedrive_file_schema():
    mod = _load_tools()
    tool = next(t for t in mod.TOOL_DEFS if t["name"] == "move_onedrive_file")
    props = tool["input_schema"]["properties"]
    required = tool["input_schema"].get("required", [])
    for field in ("source_drive_id", "source_item_id", "dest_drive_id", "dest_folder_id"):
        assert field in props, f"move_onedrive_file missing prop {field}"
        assert field in required, f"move_onedrive_file {field} not required"


def test_copy_onedrive_file_schema():
    mod = _load_tools()
    tool = next(t for t in mod.TOOL_DEFS if t["name"] == "copy_onedrive_file")
    props = tool["input_schema"]["properties"]
    required = tool["input_schema"].get("required", [])
    for field in ("source_drive_id", "source_item_id", "dest_drive_id", "dest_folder_id"):
        assert field in props, f"copy_onedrive_file missing prop {field}"
        assert field in required, f"copy_onedrive_file {field} not required"
    assert "new_name" in props, "copy_onedrive_file missing optional new_name"


def test_get_onedrive_item_schema():
    mod = _load_tools()
    tool = next(t for t in mod.TOOL_DEFS if t["name"] == "get_onedrive_item")
    props = tool["input_schema"]["properties"]
    required = tool["input_schema"].get("required", [])
    assert "drive_id" in props
    assert "item_id" in props
    assert "drive_id" in required
    assert "item_id" in required


def test_read_onedrive_file_accepts_drive_id():
    mod = _load_tools()
    tool = next(t for t in mod.TOOL_DEFS if t["name"] == "read_onedrive_file")
    props = tool["input_schema"]["properties"]
    assert "drive_id" in props, "read_onedrive_file missing drive_id param"


def test_list_onedrive_files_accepts_drive_id():
    mod = _load_tools()
    tool = next(t for t in mod.TOOL_DEFS if t["name"] == "list_onedrive_files")
    props = tool["input_schema"]["properties"]
    assert "drive_id" in props, "list_onedrive_files missing drive_id param"


def test_resolve_teams_attachment_direct_fetch_by_message_id():
    """resolve_teams_attachment uses the single-message chatsvc endpoint directly.

    The Teams deep-link message_id (e.g. 1787611789532) is the epoch-ms composetime
    used as the Skype message id.  The tool should call
    GET /v1/users/ME/conversations/{chatId}/messages/{messageId}
    directly — deterministic, no pagination required.
    """
    import sys
    import types
    import base64
    import urllib.parse
    import unittest.mock as _mock
    import importlib

    SHARE_URL = "https://tenant.sharepoint.com/:b:/s/site/ABCDEF?e=xyz123"
    FAKE_HTML = (
        f'<URIObject type="File.1">'
        f'<Title>Feedback form.pdf</Title>'
        f'<OriginalName v="Feedback form.pdf" />'
        f'<a href="{SHARE_URL}">Feedback form.pdf</a>'
        f'</URIObject>'
    )
    FAKE_MESSAGE_ID = "1787611789532"
    CHAT_ID = "19:2870f29cb7fd490c84fd8d51985ee2ca@thread.v2"

    fetched_urls = []

    def fake_get(url, token):
        fetched_urls.append(url)
        if f"/messages/{FAKE_MESSAGE_ID}" in url:
            return {"id": FAKE_MESSAGE_ID, "content": FAKE_HTML, "composetime": FAKE_MESSAGE_ID}
        return {"messages": [], "_metadata": {}}

    fake_rc = types.ModuleType("_teams_read_chats_for_attach")
    fake_rc.get_auth = lambda: ("SKYPETOKEN", "https://chatsvc.example.com/v1")
    fake_rc._get = fake_get
    sys.modules["_teams_read_chats_for_attach"] = fake_rc

    expected_b64 = base64.urlsafe_b64encode(SHARE_URL.encode()).decode().rstrip("=")
    expected_token = f"u!{expected_b64}"
    captured_gc_paths = []

    class FakeGC:
        def get(self, path, params=None):
            captured_gc_paths.append(path)
            return {
                "id": "ITEMID123",
                "name": "Feedback form.pdf",
                "size": 42000,
                "webUrl": SHARE_URL,
                "parentReference": {"driveId": "DRIVEID456"},
                "@microsoft.graph.downloadUrl": "https://dl.example.com/file",
            }

    onedrive_mod = importlib.import_module("skills.onedrive.tools")
    with _mock.patch("skills._m365.helpers.get_skill_client", return_value=FakeGC()):
        result = onedrive_mod._tool_resolve_teams_attachment(
            chat_id=CHAT_ID,
            message_id=FAKE_MESSAGE_ID,
        )

    assert result.get("item_id") == "ITEMID123", f"unexpected result: {result}"
    assert result.get("drive_id") == "DRIVEID456"
    assert result.get("filename") == "Feedback form.pdf"
    assert result.get("size") == 42000

    assert any(f"/messages/{FAKE_MESSAGE_ID}" in u for u in fetched_urls), (
        f"Expected direct single-message fetch, got URLs: {fetched_urls}"
    )
    assert not any("/messages?" in u or "pageSize" in u for u in fetched_urls), (
        f"Should not have done a paginated list fetch, got: {fetched_urls}"
    )
    assert urllib.parse.quote(expected_token, safe="!") in captured_gc_paths[0]


def test_resolve_teams_attachment_urlsrc_pattern():
    """resolve_teams_attachment also extracts urlsrc= and url= attribute patterns."""
    import sys
    import types
    import importlib
    import unittest.mock as _mock

    SHARE_URL = "https://tenant.sharepoint.com/sites/x/_layouts/doc.aspx?sourcedoc=ABC"
    FAKE_HTML = (
        f'<span><a urlsrc="{SHARE_URL}" type="fileInfo">Feedback form.docx</a></span>'
    )
    FAKE_MESSAGE_ID = "1111111111111"

    fake_rc = types.ModuleType("_teams_read_chats_for_attach")
    fake_rc.get_auth = lambda: ("TOK", "https://chatsvc.example.com/v1")
    fake_rc._get = lambda url, token: (
        {"id": FAKE_MESSAGE_ID, "content": FAKE_HTML}
        if f"/messages/{FAKE_MESSAGE_ID}" in url else {"messages": [], "_metadata": {}}
    )
    sys.modules["_teams_read_chats_for_attach"] = fake_rc

    class FakeGC:
        def get(self, path, params=None):
            return {
                "id": "ID999", "name": "Feedback form.docx", "size": 1000,
                "webUrl": SHARE_URL, "parentReference": {"driveId": "DRV999"},
                "@microsoft.graph.downloadUrl": "",
            }

    onedrive_mod = importlib.import_module("skills.onedrive.tools")
    with _mock.patch("skills._m365.helpers.get_skill_client", return_value=FakeGC()):
        result = onedrive_mod._tool_resolve_teams_attachment(
            chat_id="19:abc@thread.v2", message_id=FAKE_MESSAGE_ID,
        )

    assert result.get("item_id") == "ID999", f"unexpected: {result}"
    assert result.get("filename") == "Feedback form.docx"


def test_resolve_teams_attachment_no_links_returns_raw_content():
    """When no file links are found, the tool returns message_found=True and the raw content."""
    import sys
    import types
    import importlib
    import unittest.mock as _mock

    FAKE_MESSAGE_ID = "2222222222222"
    FAKE_HTML = "<p>Hey, just checking in!</p>"

    fake_rc = types.ModuleType("_teams_read_chats_for_attach")
    fake_rc.get_auth = lambda: ("TOK", "https://chatsvc.example.com/v1")
    fake_rc._get = lambda url, token: (
        {"id": FAKE_MESSAGE_ID, "content": FAKE_HTML}
        if f"/messages/{FAKE_MESSAGE_ID}" in url else {"messages": [], "_metadata": {}}
    )
    sys.modules["_teams_read_chats_for_attach"] = fake_rc

    onedrive_mod = importlib.import_module("skills.onedrive.tools")
    result = onedrive_mod._tool_resolve_teams_attachment(
        chat_id="19:abc@thread.v2", message_id=FAKE_MESSAGE_ID,
    )

    assert "error" in result
    assert result.get("message_found") is True
    assert FAKE_HTML in result.get("content_html", ""), f"raw content missing: {result}"
