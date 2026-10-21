"""Pinned OneNote pages carry a site_id so team pages can be edited."""

import pathlib

import pytest

from skills.onenote import state
from skills.onenote import tools as onenote_tools

CHAT_SRC = (pathlib.Path(__file__).parent.parent / "web" / "routes" / "chat.py").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _clean_pins():
    state.pinned_onenote_pages.clear()
    yield
    state.pinned_onenote_pages.clear()


def test_pin_stores_site_id():
    onenote_tools._tool_pin_onenote_page("p1", "Plan", "NB", "Sec", site_id="contoso,aaa,bbb")
    assert state.pinned_onenote_pages["plan"]["site_id"] == "contoso,aaa,bbb"


def test_pin_without_site_id_stores_empty_string():
    onenote_tools._tool_pin_onenote_page("p1", "Plan")
    assert state.pinned_onenote_pages["plan"]["site_id"] == ""


def test_pin_site_text():
    assert state.pin_site_text("contoso,aaa,bbb") == ", site_id: contoso,aaa,bbb"
    assert state.pin_site_text("") == ""
    assert state.pin_site_text(None) == ""


def test_chat_prompt_uses_pin_site_text_in_both_pin_lines():
    assert CHAT_SRC.count("pin_site_text(") == 2


SITE = "contoso.sharepoint.com,11111111-1111-1111-1111-111111111111,22222222-2222-2222-2222-222222222222"
TEAM_URL = "https://contoso.sharepoint.com/sites/Team/_layouts/15/Doc.aspx?sourcedoc=x&action=edit"


class _FakeGC:
    def __init__(self):
        self.calls = []

    def get(self, path, params=None):
        self.calls.append(path)
        return {"id": SITE}


def test_resolve_pin_site_id_team_url(monkeypatch):
    gc = _FakeGC()
    monkeypatch.setattr("skills._m365.helpers.get_skill_client", lambda *_: gc)
    assert onenote_tools.resolve_pin_site_id(TEAM_URL) == SITE
    assert gc.calls == ["/sites/contoso.sharepoint.com:/sites/Team"]


@pytest.mark.parametrize(
    "url",
    ["", "https://www.onenote.com/notebooks", "https://contoso-my.sharepoint.com/personal/a_b_com/_layouts/15/Doc.aspx", "Team"],
)
def test_resolve_pin_site_id_not_a_team_site_makes_no_graph_call(monkeypatch, url):
    gc = _FakeGC()
    monkeypatch.setattr("skills._m365.helpers.get_skill_client", lambda *_: gc)
    assert onenote_tools.resolve_pin_site_id(url) == ""
    assert gc.calls == []


def test_resolve_pin_site_id_graph_failure_returns_empty(monkeypatch):
    class Boom:
        def get(self, *a, **k):
            raise RuntimeError("403")

    monkeypatch.setattr("skills._m365.helpers.get_skill_client", lambda *_: Boom())
    assert onenote_tools.resolve_pin_site_id(TEAM_URL) == ""


def _pin(monkeypatch, meta, site):
    import asyncio

    from routes import onenote as routes_onenote

    saved = {}
    monkeypatch.setattr(
        "skills.context.state.set_pin",
        lambda source, pid, label, m, ctx: saved.update(meta=m) or {"pinned": True},
    )
    monkeypatch.setattr("skills.onenote.tools.resolve_pin_site_id", lambda url: site)
    req = routes_onenote.ContextPinRequest(source="onenote", id="title:Page", label="Page", meta=meta)
    asyncio.run(routes_onenote.context_pin(req))
    return saved["meta"]


def test_context_pin_stores_resolved_site_id(monkeypatch):
    meta = _pin(monkeypatch, {"kind": "page", "notebook": "NB", "web_url": TEAM_URL}, SITE)
    assert meta["site_id"] == SITE
    assert state.pinned_onenote_pages["page"]["site_id"] == SITE


def test_context_pin_unresolved_site_still_pins(monkeypatch):
    meta = _pin(monkeypatch, {"kind": "page", "notebook": "NB", "web_url": TEAM_URL}, "")
    assert "site_id" not in meta
    assert state.pinned_onenote_pages["page"]["site_id"] == ""


def test_title_pin_prompt_hands_over_site_id():
    assert "(site_id: {m['site_id']})" in CHAT_SRC
