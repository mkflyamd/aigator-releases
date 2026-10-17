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


# ── update_onenote_page ──────────────────────────────────────────────────────

def test_update_default_is_todays_request_and_result():
    gc = FakeGC()
    result = _run(onenote_tools._tool_update_onenote_page, gc, "page1", "hello <x>")
    assert result == {"updated": True, "page_id": "page1"}
    assert gc.methods() == ["PATCH"]
    method, url, _ = gc.calls[0]
    assert url == "https://graph.microsoft.com/v1.0/me/onenote/pages/page1/content"
    assert gc.patch_bodies() == [
        [{"target": "body", "action": "append", "content": "<div>hello &lt;x&gt;</div>"}]
    ]


def test_update_encodes_page_id():
    gc = FakeGC()
    _run(onenote_tools._tool_update_onenote_page, gc, SLASH_ID, "hello")
    assert "%2F" in gc.calls[0][1]


def test_update_routes_to_team_site():
    gc = FakeGC()
    _run(onenote_tools._tool_update_onenote_page, gc, "page1", "hello", site_id=SITE)
    assert "/sites/contoso.sharepoint.com%2Caaa%2Cbbb/onenote/pages/page1/content" in gc.calls[0][1]


def test_update_replace_element_returns_previous_html_and_fresh_outline():
    gc = FakeGC()
    result = _run(
        onenote_tools._tool_update_onenote_page,
        gc,
        "page1",
        "<table><tr><td>new</td></tr></table>",
        html=True,
        action="replace",
        target="table:{a}{7}",
    )
    assert gc.methods() == ["GET", "PATCH", "GET"]
    assert gc.patch_bodies() == [
        [{"target": "table:{a}{7}", "action": "replace", "content": "<table><tr><td>new</td></tr></table>"}]
    ]
    assert result["updated"] is True
    assert result["previous_html"].startswith("<table")
    assert "id=" not in result["previous_html"]
    assert [e["tag"] for e in result["elements"]] == ["h1", "p", "table"]


def test_update_previous_html_is_capped(monkeypatch):
    monkeypatch.setattr(page_edit, "MAX_PREVIOUS_HTML", 12)
    gc = FakeGC()
    result = _run(
        onenote_tools._tool_update_onenote_page, gc, "page1", "x", action="replace", target="table:{a}{7}"
    )
    assert len(result["previous_html"]) == 12


def test_update_unknown_target_sends_nothing():
    gc = FakeGC()
    result = _run(
        onenote_tools._tool_update_onenote_page, gc, "page1", "x", action="replace", target="p:{zz}{1}"
    )
    assert result["error"] == "target_not_found"
    assert "PATCH" not in gc.methods()


def test_update_replace_body_is_refused_before_any_call():
    gc = FakeGC()
    result = _run(
        onenote_tools._tool_update_onenote_page, gc, "page1", "x", action="replace", target="body"
    )
    assert result["error"] == "replace_body_not_allowed"
    assert gc.calls == []


def test_update_empty_replace_sends_empty_paragraph():
    gc = FakeGC()
    _run(onenote_tools._tool_update_onenote_page, gc, "page1", "", action="replace", target="p:{a}{3}")
    assert gc.patch_bodies()[0][0]["content"] == "<p></p>"


async def test_execute_tool_empty_replace_reaches_the_tool(monkeypatch):
    import shared
    from app import execute_tool

    gc = FakeGC()
    monkeypatch.setitem(
        shared.TOOL_DISPATCH, "update_onenote_page", onenote_tools._tool_update_onenote_page
    )
    with patch("skills._m365.helpers.get_skill_client", return_value=gc):
        result = await execute_tool(
            "update_onenote_page",
            {"page_id": "page1", "content": "", "action": "replace", "target": "p:{a}{3}"},
        )
    assert result.get("error") != "missing_required_params"
    assert gc.patch_bodies()[0][0]["content"] == "<p></p>"


def test_update_refuses_content_the_scrubber_removed_text_from():
    import content_guard

    gc = FakeGC()
    result = _run(
        onenote_tools._tool_update_onenote_page,
        gc,
        "page1",
        f"before {content_guard.REMOVED} after",
    )
    assert result["error"] == "content_was_filtered"
    assert gc.calls == []


def test_update_previous_html_truncated_flag(monkeypatch):
    monkeypatch.setattr(page_edit, "MAX_PREVIOUS_HTML", 12)
    gc = FakeGC()
    result = _run(
        onenote_tools._tool_update_onenote_page, gc, "page1", "x", action="replace", target="table:{a}{7}"
    )
    assert result["previous_html_truncated"] is True
    monkeypatch.setattr(page_edit, "MAX_PREVIOUS_HTML", 1000)
    gc = FakeGC()
    result = _run(
        onenote_tools._tool_update_onenote_page, gc, "page1", "x", action="replace", target="p:{a}{3}"
    )
    assert "previous_html_truncated" not in result


def test_update_null_action_and_target_default_to_append_body():
    gc = FakeGC()
    result = _run(
        onenote_tools._tool_update_onenote_page, gc, "page1", "hello", action=None, target=None
    )
    assert result == {"updated": True, "page_id": "page1"}
    assert gc.methods() == ["PATCH"]
    assert gc.patch_bodies()[0][0]["target"] == "body"


def test_update_title_needs_no_preread_and_returns_outline():
    gc = FakeGC()
    result = _run(
        onenote_tools._tool_update_onenote_page, gc, "page1", "New title", action="replace", target="title"
    )
    assert gc.methods() == ["PATCH", "GET"]
    assert gc.patch_bodies() == [[{"target": "title", "action": "replace", "content": "New title"}]]
    assert "previous_html" not in result
    assert "elements" in result


def test_update_insert_before_element():
    gc = FakeGC()
    _run(
        onenote_tools._tool_update_onenote_page,
        gc,
        "page1",
        "added",
        action="insert",
        target="p:{a}{3}",
        position="before",
    )
    assert gc.patch_bodies()[0][0] == {
        "target": "p:{a}{3}",
        "action": "insert",
        "content": "<p>added</p>",
        "position": "before",
    }


class _NotFound(RuntimeError):
    status_code = 404


def test_update_404_without_site_adds_team_hint():
    gc = FakeGC(patch_error=_NotFound("Graph API 404: not found"))
    result = _run(onenote_tools._tool_update_onenote_page, gc, "page1", "x")
    assert "404" in result["error"]
    assert "site_id" in result["hint"]


def test_update_404_with_site_has_no_hint():
    gc = FakeGC(patch_error=_NotFound("Graph API 404: not found"))
    result = _run(onenote_tools._tool_update_onenote_page, gc, "page1", "x", site_id=SITE)
    assert "hint" not in result


def test_update_other_graph_error_is_returned_as_error():
    class _Bad(RuntimeError):
        status_code = 400

    gc = FakeGC(patch_error=_Bad("Graph API 400: bad"))
    result = _run(onenote_tools._tool_update_onenote_page, gc, "page1", "x")
    assert result == {"error": "Graph API 400: bad"}


def test_list_sections_by_site_only():
    from skills.onenote import tools

    class SectionsGC:
        def __init__(self):
            self.paths = []

        def get(self, path, params=None):
            self.paths.append(path)
            return {"value": [{"id": "s1", "displayName": "Start Here"}]}

    gc = SectionsGC()
    with patch("skills._m365.helpers.get_skill_client", return_value=gc):
        out = tools._tool_list_onenote_sections(site_id="host,11111111-1111-1111-1111-111111111111,22222222-2222-2222-2222-222222222222")
    assert gc.paths == ["/sites/host%2C11111111-1111-1111-1111-111111111111%2C22222222-2222-2222-2222-222222222222/onenote/sections"]
    assert out["sections"][0]["name"] == "Start Here"
    assert out["sections"][0]["site_id"] == "host,11111111-1111-1111-1111-111111111111,22222222-2222-2222-2222-222222222222"


def test_list_sections_needs_notebook_or_site():
    from skills.onenote import tools

    assert "error" in tools._tool_list_onenote_sections()


def test_list_sections_resolves_site_url():
    from skills.onenote import tools

    class UrlGC:
        def __init__(self):
            self.paths = []

        def get(self, path, params=None):
            self.paths.append(path)
            if path.endswith("onenote/sections"):
                return {"value": [{"id": "s1", "displayName": "Start Here"}]}
            return {"id": "host.example,11111111-1111-1111-1111-111111111111,22222222-2222-2222-2222-222222222222"}

    gc = UrlGC()
    url = "https://host.example/sites/SiloEngineering/_layouts/15/Doc.aspx?sourcedoc=x"
    with patch("skills._m365.helpers.get_skill_client", return_value=gc):
        out = tools._tool_list_onenote_sections(site_id=url)
    assert gc.paths[0] == "/sites/host.example:/sites/SiloEngineering"
    assert out["sections"][0]["site_id"].startswith("host.example,1111")


def test_list_sections_resolves_site_name_and_reports_unknown():
    from skills.onenote import tools

    class NameGC:
        def get(self, path, params=None):
            if path == "/sites":
                return {"value": [{"id": "h,1,2", "displayName": "Other"}, {"id": "h2,3,4", "displayName": "SiloEngineering"}]}
            return {"value": []}

    with patch("skills._m365.helpers.get_skill_client", return_value=NameGC()):
        assert "sections" in tools._tool_list_onenote_sections(site_id="siloengineering")
        out = tools._tool_list_onenote_sections(site_id="Nope")
    assert "error" in out
