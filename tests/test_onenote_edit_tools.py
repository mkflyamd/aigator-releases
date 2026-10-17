"""update/read OneNote page tools with a fake Graph client."""

import json
from unittest.mock import patch

import pytest

from skills.onenote import page_edit
from skills.onenote import tools as onenote_tools

PAGE = """<html><head><title>T</title></head><body>
<div id="div:{a}{1}" style="position:absolute;left:48px;top:120px">
<h1 id="h1:{a}{2}">Heading one</h1>
<p id="p:{a}{3}">Paragraph one</p>
<table id="table:{a}{7}"><tr id="tr:{a}{8}"><td id="td:{a}{9}"><p id="p:{a}{10}">r1c1</p></td></tr></table>
</div></body></html>"""

SLASH_ID = "AAMkAD/item+Id=xQ=="
SITE = "contoso.sharepoint.com,aaa,bbb"


class FakeResp:
    def __init__(self, text=""):
        self.text = text
        self.status_code = 200


class FakeGC:
    def __init__(self, page_html=PAGE, patch_error=None):
        self.page_html = page_html
        self.patch_error = patch_error
        self.calls = []

    def _headers(self):
        return {"Authorization": "Bearer aigator-fake-api-key"}

    def get_token(self):
        return "aigator-fake-api-key"

    def get(self, path, params=None):
        self.calls.append(("META", path, None))
        return {"title": "My page", "lastModifiedDateTime": "2026-10-17T10:00:00Z"}

    def _request(self, method, url, **kw):
        self.calls.append((method, url, kw.get("content")))
        if method == "PATCH" and self.patch_error:
            raise self.patch_error
        return FakeResp(self.page_html if method == "GET" else "")

    def methods(self):
        return [c[0] for c in self.calls]

    def patch_bodies(self):
        return [json.loads(c[2]) for c in self.calls if c[0] == "PATCH"]


def _run(fn, gc, *args, **kwargs):
    with patch("skills._m365.helpers.get_skill_client", return_value=gc):
        return fn(*args, **kwargs)


# ── read_onenote_page ────────────────────────────────────────────────────────

def test_read_include_ids_returns_outline_for_personal_page():
    gc = FakeGC()
    result = _run(onenote_tools._tool_read_onenote_page, gc, "page1", include_ids=True)
    assert result["title"] == "My page"
    assert [e["tag"] for e in result["elements"]] == ["h1", "p", "table"]
    assert result["total"] == 3
    get_urls = [c[1] for c in gc.calls if c[0] == "GET"]
    assert get_urls == ["https://graph.microsoft.com/v1.0/me/onenote/pages/page1/content?includeIDs=true"]


def test_read_include_ids_routes_to_site_and_encodes_ids():
    gc = FakeGC()
    _run(onenote_tools._tool_read_onenote_page, gc, SLASH_ID, site_id=SITE, include_ids=True)
    url = next(c[1] for c in gc.calls if c[0] == "GET")
    assert "/sites/contoso.sharepoint.com%2Caaa%2Cbbb/onenote/pages/" in url
    assert "%2F" in url and "/item" not in url


def test_read_include_ids_paging():
    gc = FakeGC()
    result = _run(onenote_tools._tool_read_onenote_page, gc, "page1", include_ids=True, offset=1, limit=1)
    assert [e["tag"] for e in result["elements"]] == ["p"]
    assert result["next_offset"] == 2


def test_read_element_id_returns_html_without_ids():
    gc = FakeGC()
    result = _run(onenote_tools._tool_read_onenote_page, gc, "page1", element_id="table:{a}{7}")
    assert result["id"] == "table:{a}{7}"
    assert result["html"].startswith("<table")
    assert "id=" not in result["html"]


def test_read_element_id_unknown_is_target_not_found():
    gc = FakeGC()
    result = _run(onenote_tools._tool_read_onenote_page, gc, "page1", element_id="p:{x}{9}")
    assert result["error"] == "target_not_found"


def test_read_element_id_too_large(monkeypatch):
    monkeypatch.setattr(page_edit, "MAX_ELEMENT_HTML", 10)
    gc = FakeGC()
    result = _run(onenote_tools._tool_read_onenote_page, gc, "page1", element_id="table:{a}{7}")
    assert result["error"] == "element_too_large"
