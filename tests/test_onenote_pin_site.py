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
