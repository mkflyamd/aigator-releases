"""OneDrive pin open must resolve a web_url when the pin lacks one — Issue #60.

Some OneDrive pins are created without a `web_url` (e.g. the folder-browse path in
third-pane.js omits it), so clicking "open" fell back to opening the OneDrive root
pane instead of the actual file. The fix adds a GET endpoint that resolves an
item's webUrl from Graph by item_id (+ optional drive_id for SharePoint), so the
front end can open the real file.
"""
import pathlib
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from app import app

APP_JS = (pathlib.Path(__file__).parent.parent / "static" / "app.js").read_text(encoding="utf-8")


def _graph_returning(web_url: str):
    gc = MagicMock()
    gc.get.return_value = {"id": "ITEM1", "name": "Doc.docx", "webUrl": web_url}
    return gc


class TestResolveItemWebUrl:
    def test_get_item_returns_web_url_from_personal_drive(self):
        client = TestClient(app)
        url = "https://amd-my.sharepoint.com/personal/x/Doc.docx"
        with patch("skills._m365.helpers.get_graph_client", return_value=_graph_returning(url)) as g:
            r = client.get("/api/onedrive/items/ITEM1")
        assert r.status_code == 200, r.text
        assert r.json()["web_url"] == url
        # Personal drive path (no drive_id) must target /me/drive/items/<id>.
        called_path = g.return_value.get.call_args.args[0]
        assert called_path == "/me/drive/items/ITEM1"

    def test_get_item_uses_drive_id_for_sharepoint(self):
        client = TestClient(app)
        url = "https://amd.sharepoint.com/sites/team/Doc.docx"
        with patch("skills._m365.helpers.get_graph_client", return_value=_graph_returning(url)) as g:
            r = client.get("/api/onedrive/items/ITEM1?drive_id=DRIVE9")
        assert r.status_code == 200, r.text
        assert r.json()["web_url"] == url
        called_path = g.return_value.get.call_args.args[0]
        assert called_path == "/drives/DRIVE9/items/ITEM1"


class TestResolveItemValidation:
    """drive_id/item_id are interpolated into the Graph path, so they must be
    validated like the other drive-id handlers to block path/query injection."""

    def test_malicious_drive_id_rejected(self):
        client = TestClient(app)
        gc = _graph_returning("https://x")
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = client.get("/api/onedrive/items/ITEM1", params={"drive_id": "abc?$expand=children"})
        assert r.status_code == 400, r.text
        # The Graph client must never have been called with injected input.
        assert gc.get.call_count == 0

    def test_malicious_item_id_rejected(self):
        client = TestClient(app)
        gc = _graph_returning("https://x")
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = client.get("/api/onedrive/items/has space?and=q")
        assert r.status_code in (400, 404), r.text
        assert gc.get.call_count == 0


class TestPinOpenResolvesWebUrl:
    """The OneDrive pin 'open' handler must resolve web_url via the endpoint
    when the pin lacks one, instead of opening the OneDrive root pane."""

    def test_onedrive_pin_open_calls_resolve_endpoint(self):
        idx = APP_JS.find("else if (p.source === 'onedrive')")
        assert idx != -1, "onedrive pin-open branch not found in app.js"
        branch = APP_JS[idx:idx + 1500]
        assert "/api/onedrive/items/" in branch, (
            "onedrive pin-open must resolve the file URL via "
            "/api/onedrive/items/<id> when web_url is absent (#60)."
        )
        assert "data.web_url" in branch and "window.open" in branch, (
            "resolved web_url must be opened in the browser (#60)."
        )

    def test_placeholder_tab_keeps_window_handle(self):
        """Opening the synchronous placeholder tab with 'noopener' makes
        window.open return null, so the redirect can never fire and it always
        falls back to the OneDrive pane (#60). The placeholder must be opened
        WITHOUT noopener and then navigated via its retained handle."""
        idx = APP_JS.find("else if (p.source === 'onedrive')")
        assert idx != -1
        branch = APP_JS[idx:idx + 1500]
        assert "win.location" in branch, "must navigate the opened tab via its handle"
        # The placeholder (blank) open must NOT use noopener — that returns null
        # and breaks the redirect. The direct open of a known webUrl above may
        # keep noopener; only the placeholder-then-redirect path is at issue.
        assert "window.open('', '_blank', 'noopener')" not in branch, (
            "placeholder tab opened with noopener nulls the handle (#60)."
        )
        assert "window.open('about:blank', '_blank')" in branch, (
            "open the placeholder tab as about:blank without noopener so the "
            "retained handle can be redirected to the resolved URL (#60)."
        )
