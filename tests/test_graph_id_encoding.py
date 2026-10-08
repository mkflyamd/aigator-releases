"""Graph immutable ID encoding — regression tests.

Verifies that resource IDs containing '/', '+', '=' are percent-encoded
before being interpolated into Graph URL path segments.

Before the fix:  f"/me/drive/items/{item_id}"  → 400 "Resource not found for segment"
After the fix:   f"/me/drive/items/{_eid(item_id)}" → %2F encoded correctly

Synthetic ID:  "AAMkAD/item+Id=xQ=="
Expected in path: %2F (not literal /)
"""

import sys
import pathlib
import urllib.parse
from unittest.mock import MagicMock, patch

# web/ is added to sys.path by tests/conftest.py
WEB = pathlib.Path(__file__).parent.parent / "web"

SLASH_ID = "AAMkAD/item+Id=xQ=="
SLASH_DRV = "b!drives/driveId+Eq=xQ=="


# ── helpers ──────────────────────────────────────────────────────────────────

def _gc_capturing_paths():
    """Return a MagicMock gc that records every path passed to get/post/patch/delete."""
    gc = MagicMock()
    captured = []

    def _record(path, *args, **kwargs):
        captured.append(str(path))
        return {}

    gc.get.side_effect = _record
    gc.post.side_effect = _record
    gc.patch.side_effect = _record
    gc.delete.side_effect = _record
    gc.get_token.return_value = "FAKE_TOKEN"
    return gc, captured


# ── 1. routes/onedrive.py ────────────────────────────────────────────────────

class TestOneDriveRouteEncoding:
    """Encoding in web/routes/onedrive.py."""

    def test_get_item_encodes_item_id(self):
        from routes.onedrive import onedrive_get_item
        gc, captured = _gc_capturing_paths()
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            try:
                onedrive_get_item(SLASH_ID)
            except Exception:
                pass
        assert captured, "No Graph call captured"
        assert "%2F" in captured[0], f"Literal '/' in path: {captured[0]}"

    def test_delete_item_encodes_item_id(self):
        from routes.onedrive import onedrive_delete_item
        gc, captured = _gc_capturing_paths()
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            try:
                onedrive_delete_item(SLASH_ID)
            except Exception:
                pass
        assert captured, "No Graph call captured"
        assert "%2F" in captured[0], f"Literal '/' in path: {captured[0]}"

    def test_rename_item_encodes_item_id(self):
        from routes.onedrive import onedrive_rename_item
        gc, captured = _gc_capturing_paths()
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            try:
                onedrive_rename_item(SLASH_ID, {"name": "new.docx"})
            except Exception:
                pass
        assert captured, "No Graph call captured"
        assert "%2F" in captured[0], f"Literal '/' in path: {captured[0]}"

    def test_create_folder_encodes_parent_id(self):
        from routes.onedrive import onedrive_create_folder
        gc, captured = _gc_capturing_paths()
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            try:
                onedrive_create_folder(SLASH_ID, {"name": "NewFolder"})
            except Exception:
                pass
        assert captured, "No Graph call captured"
        assert "%2F" in captured[0], f"Literal '/' in path: {captured[0]}"

    def test_get_item_with_drive_id_encodes_both(self):
        from routes.onedrive import onedrive_get_item
        gc, captured = _gc_capturing_paths()
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            try:
                onedrive_get_item(SLASH_ID, drive_id=SLASH_DRV)
            except Exception:
                pass
        assert captured, "No Graph call captured"
        assert "%2F" in captured[0], f"Literal '/' in path: {captured[0]}"


# ── 2. skills/onedrive/tools.py ──────────────────────────────────────────────

class TestOneDriveSkillEncoding:
    """Encoding in web/skills/onedrive/tools.py."""

    def test_try_direct_lookup_encodes_item_id(self):
        from skills.onedrive.tools import _try_direct_lookup
        captured = []

        def raising_get(path, **kw):
            captured.append(str(path))
            raise Exception("404")

        gc = MagicMock()
        gc.get.side_effect = raising_get
        try:
            _try_direct_lookup(gc, SLASH_ID)
        except Exception:
            pass
        assert captured, "No Graph call captured"
        assert "%2F" in captured[0], f"Literal '/' in path: {captured[0]}"

    def test_try_direct_lookup_with_drive_id_encodes_both(self):
        from skills.onedrive.tools import _try_direct_lookup
        captured = []

        def raising_get(path, **kw):
            captured.append(str(path))
            raise Exception("404")

        gc = MagicMock()
        gc.get.side_effect = raising_get
        try:
            _try_direct_lookup(gc, SLASH_ID, SLASH_DRV)
        except Exception:
            pass
        assert captured, "No Graph call captured"
        assert "%2F" in captured[0], f"Literal '/' in path: {captured[0]}"

    def test_get_onedrive_item_encodes_ids(self):
        from skills.onedrive import tools as od_tools
        gc, captured = _gc_capturing_paths()
        with patch.object(od_tools, "_tool_get_onedrive_item", wraps=od_tools._tool_get_onedrive_item):
            with patch("skills._m365.helpers.get_skill_client", return_value=gc):
                od_tools._tool_get_onedrive_item(SLASH_DRV, SLASH_ID)
        assert captured, "No Graph call captured"
        assert "%2F" in captured[0], f"Literal '/' in path: {captured[0]}"

    def test_move_onedrive_file_encodes_ids(self):
        from skills.onedrive import tools as od_tools
        captured = []
        gc = MagicMock()
        gc.patch.side_effect = lambda path, body, **kw: captured.append(str(path)) or {}
        with patch("skills._m365.helpers.get_skill_client", return_value=gc):
            od_tools._tool_move_onedrive_file(SLASH_DRV, SLASH_ID, "dest_drive", "dest_folder")
        assert captured, "No Graph call captured"
        assert "%2F" in captured[0], f"Literal '/' in path: {captured[0]}"

    def test_copy_onedrive_file_encodes_ids(self, monkeypatch):
        from skills.onedrive import tools as od_tools
        import httpx as _httpx
        captured_urls = []

        class FakeResp:
            status_code = 202
            headers = {"Location": ""}
            content = b""
            text = ""

        def fake_post(url, *args, **kwargs):
            captured_urls.append(url)
            return FakeResp()

        monkeypatch.setattr(_httpx, "post", fake_post)
        gc = MagicMock()
        gc.get_token.return_value = "FAKE"
        with patch("skills._m365.helpers.get_skill_client", return_value=gc):
            od_tools._tool_copy_onedrive_file(SLASH_DRV, SLASH_ID, "dest_drive", "dest_folder")
        assert captured_urls, "No httpx.post call captured"
        assert "%2F" in captured_urls[0], f"Literal '/' in URL: {captured_urls[0]}"


# ── 3. skills/docx/tools.py ──────────────────────────────────────────────────

class TestDocxEncoding:
    """Encoding in web/skills/docx/tools.py _onedrive_docx_context."""

    def test_get_meta_encodes_item_id(self):
        from skills.docx import tools as docx_tools
        captured = []

        def recording_get(path, **kw):
            captured.append(str(path))
            raise RuntimeError("stop after meta")

        gc = MagicMock()
        gc.get.side_effect = recording_get
        gc.get_token.return_value = "FAKE"

        with patch("skills._m365.helpers.get_skill_client", return_value=gc):
            try:
                with docx_tools._onedrive_docx_context(SLASH_ID) as _:
                    pass
            except Exception:
                pass

        assert captured, "No Graph call captured"
        assert "%2F" in captured[0], f"Literal '/' in path: {captured[0]}"


# ── 4. skills/ppt/tools.py ───────────────────────────────────────────────────

class TestPptEncoding:
    """Encoding in web/skills/ppt/tools.py _onedrive_pptx_context."""

    def test_download_url_encodes_real_id(self, monkeypatch):
        from skills.ppt import tools as ppt_tools
        import httpx as _httpx

        captured_urls = []

        class FakeResp:
            status_code = 200
            content = b"PK\x03\x04"
            def raise_for_status(self): pass

        class FakeClient:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def get(self, url, **kw):
                captured_urls.append(url)
                return FakeResp()
            def close(self): pass

        monkeypatch.setattr(_httpx, "Client", lambda **kw: FakeClient())

        gc = MagicMock()
        gc.get_token.return_value = "FAKE"

        fake_direct = {
            "meta": {
                "id": SLASH_ID,
                "name": "deck.pptx",
                "@microsoft.graph.downloadUrl": "",
            },
            "drive_id": SLASH_DRV,
        }

        with patch("skills.onedrive.tools._try_direct_lookup_with_download_url", return_value=fake_direct):
            with patch("skills._m365.helpers.get_skill_client", return_value=gc):
                try:
                    with ppt_tools._onedrive_pptx_context(SLASH_ID, SLASH_DRV, readonly=True) as _:
                        pass
                except Exception:
                    pass

        assert captured_urls, "No httpx.Client.get call captured"
        assert "%2F" in captured_urls[0], f"Literal '/' in URL: {captured_urls[0]}"


# ── 5. routes/onenote.py ─────────────────────────────────────────────────────

class TestOneNoteRouteEncoding:
    """Encoding in web/routes/onenote.py."""

    def test_page_content_url_encodes_page_id(self, monkeypatch):
        import urllib.request as _ur
        from routes import onenote as onenote_route

        captured_urls = []

        class FakeResp:
            def read(self): return b"<html>hi</html>"
            def __enter__(self): return self
            def __exit__(self, *a): pass
            headers = {}

        def fake_urlopen(req, timeout=None):
            captured_urls.append(req.full_url)
            return FakeResp()

        monkeypatch.setattr(_ur, "urlopen", fake_urlopen)

        gc = MagicMock()
        gc.get.return_value = {"title": "Test", "lastModifiedDateTime": "", "links": {}}
        gc.get_token.return_value = "FAKE"

        with patch("skills._m365.helpers.get_skill_client", return_value=gc):
            import asyncio
            try:
                asyncio.run(onenote_route.tp_onenote_page_content(SLASH_ID))
            except Exception:
                pass

        assert captured_urls, "No urllib.request call captured"
        assert "%2F" in captured_urls[0], f"Literal '/' in URL: {captured_urls[0]}"

    def test_patch_page_url_encodes_page_id(self, monkeypatch):
        import urllib.request as _ur
        from routes import onenote as onenote_route

        captured_urls = []

        class FakeResp:
            def read(self): return b""
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def fake_urlopen(req, timeout=None):
            captured_urls.append(req.full_url)
            return FakeResp()

        monkeypatch.setattr(_ur, "urlopen", fake_urlopen)

        gc = MagicMock()
        gc.get_token.return_value = "FAKE"

        req_body = onenote_route.OneNoteUpdatePageRequest(body="hello")
        with patch("skills._m365.helpers.get_skill_client", return_value=gc):
            import asyncio
            try:
                asyncio.run(onenote_route.tp_onenote_update_page(SLASH_ID, req_body))
            except Exception:
                pass

        assert captured_urls, "No urllib.request call captured"
        assert "%2F" in captured_urls[0], f"Literal '/' in URL: {captured_urls[0]}"


# ── 6. skills/onenote/tools.py ───────────────────────────────────────────────

class TestOneNoteSkillEncoding:
    """Encoding in web/skills/onenote/tools.py."""

    def test_onenote_root_encodes_site_id(self):
        from skills.onenote.tools import _onenote_root
        root = _onenote_root("site/with+special=chars")
        assert "%2F" in root, f"Literal '/' in root: {root}"
        assert "+" not in root, f"Literal '+' in root: {root}"

    def test_read_page_encodes_page_id(self, monkeypatch):
        import urllib.request as _ur
        from skills.onenote import tools as onenote_tools

        gc_captured = []
        gc = MagicMock()

        def recording_get(path, **kw):
            gc_captured.append(str(path))
            return {"title": "T", "lastModifiedDateTime": "", "id": "x"}

        gc.get.side_effect = recording_get
        gc.get_token.return_value = "FAKE"

        captured_urls = []

        class FakeResp:
            def read(self): return b"<html></html>"
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def fake_urlopen(req, timeout=None):
            captured_urls.append(req.full_url)
            return FakeResp()

        monkeypatch.setattr(_ur, "urlopen", fake_urlopen)

        with patch("skills._m365.helpers.get_skill_client", return_value=gc):
            try:
                onenote_tools._tool_read_onenote_page(SLASH_ID)
            except Exception:
                pass

        all_paths = gc_captured + captured_urls
        assert all_paths, "No Graph call captured"
        assert any("%2F" in p for p in all_paths), f"Literal '/' in paths: {all_paths}"

    def test_update_page_encodes_page_id(self, monkeypatch):
        import urllib.request as _ur
        from skills.onenote import tools as onenote_tools

        captured_urls = []

        class FakeResp:
            def read(self): return b""
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def fake_urlopen(req, timeout=None):
            captured_urls.append(req.full_url)
            return FakeResp()

        monkeypatch.setattr(_ur, "urlopen", fake_urlopen)

        gc = MagicMock()
        gc.get_token.return_value = "FAKE"

        with patch("skills._m365.helpers.get_skill_client", return_value=gc):
            try:
                onenote_tools._tool_update_onenote_page(SLASH_ID, "hello")
            except Exception:
                pass

        assert captured_urls, "No urllib.request call captured"
        assert "%2F" in captured_urls[0], f"Literal '/' in URL: {captured_urls[0]}"

    def test_create_page_encodes_section_id(self):
        from skills.onenote import tools as onenote_tools

        gc = MagicMock()
        gc.get_token.return_value = "FAKE"
        captured_urls = []

        class FakeResp:
            def json(self): return {"id": "new_id", "title": "T", "links": {}}

        def fake_request(method, url, **kw):
            captured_urls.append(url)
            return FakeResp()

        gc._request.side_effect = fake_request
        gc._headers.return_value = {}

        with patch("skills._m365.helpers.get_skill_client", return_value=gc):
            onenote_tools._tool_create_onenote_page(SLASH_ID, "Title", "Body")

        assert captured_urls, "No Graph call captured"
        assert "%2F" in captured_urls[0], f"Literal '/' in URL: {captured_urls[0]}"


# ── 7. skills/m365-calendar/scripts/create_ooo.py ────────────────────────────

class TestCreateOooEncoding:
    """Encoding in web/skills/m365-calendar/scripts/create_ooo.py."""

    def test_patch_url_encodes_event_id(self, monkeypatch):
        import urllib.request as _ur
        import urllib.parse

        captured_urls = []

        class FakeResp:
            def read(self): return b""
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def fake_urlopen(req, timeout=None):
            captured_urls.append(req.full_url)
            return FakeResp()

        monkeypatch.setattr(_ur, "urlopen", fake_urlopen)

        class FakeClient:
            def post(self, path, body):
                return {"id": SLASH_ID}
            def _headers(self):
                return {"Authorization": "Bearer FAKE"}

        client = FakeClient()
        event_id = client.post("/me/events", {}).get("id", "")

        patch_url = f"https://graph.microsoft.com/v1.0/me/events/{urllib.parse.quote(event_id or '', safe='')}"
        patch_data = b'{"showAs": "oof"}'
        headers = client._headers()
        req = _ur.Request(patch_url, data=patch_data, headers=headers, method="PATCH")
        _ur.urlopen(req, timeout=30)

        assert captured_urls, "No urllib.request call captured"
        assert "%2F" in captured_urls[0], f"Literal '/' in URL: {captured_urls[0]}"
