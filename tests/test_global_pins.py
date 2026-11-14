import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest

from skills.context import state


@pytest.fixture(autouse=True)
def isolated_pins(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "pinned_contexts", {"default": {}})
    monkeypatch.setattr(state, "_PINS_FILE", tmp_path / "pinned_contexts.json")


def _pin(ctx="tabA", source="jira", item_id="KEY-1", label="Epic", **meta):
    state.set_pin(source, item_id, label, meta, ctx)


class TestGlobalState:
    def test_global_pin_shows_in_every_tab(self):
        _pin("tabA")
        assert state.set_pin_scope("jira", "KEY-1", "global", "tabA")["moved"] is True
        for tab in ("tabA", "tabB", "tabC"):
            pins = state.get_pins(tab)
            assert [p["id"] for p in pins] == ["KEY-1"]
            assert pins[0]["scope"] == "global"

    def test_global_pins_come_first_and_only_they_are_tagged(self):
        _pin("tabA", item_id="KEY-1")
        state.set_pin_scope("jira", "KEY-1", "global", "tabA")
        _pin("tabB", item_id="KEY-2", label="Local")
        pins = state.get_pins("tabB")
        assert [p["id"] for p in pins] == ["KEY-1", "KEY-2"]
        assert pins[0]["scope"] == "global"
        assert "scope" not in pins[1]

    def test_scope_tag_is_not_persisted(self):
        _pin("tabA")
        state.set_pin_scope("jira", "KEY-1", "global", "tabA")
        stored = state.pinned_contexts[state.GLOBAL_CONTEXT_ID]["jira::KEY-1"]
        assert "scope" not in stored
        assert "scope" not in state._PINS_FILE.read_text(encoding="utf-8")

    def test_item_in_tab_and_global_appears_once_as_global(self):
        _pin("tabA")
        state.set_pin_scope("jira", "KEY-1", "global", "tabA")
        _pin("tabB")
        pins = state.get_pins("tabB")
        assert len(pins) == 1
        assert pins[0]["scope"] == "global"

    def test_demote_lands_on_calling_tab_only(self):
        _pin("tabA")
        state.set_pin_scope("jira", "KEY-1", "global", "tabA")
        assert state.set_pin_scope("jira", "KEY-1", "tab", "tabB")["moved"] is True
        assert [p["id"] for p in state.get_pins("tabB")] == ["KEY-1"]
        assert "scope" not in state.get_pins("tabB")[0]
        assert state.get_pins("tabA") == []
        assert state.get_pins("tabC") == []

    def test_meta_survives_promote_and_demote(self):
        _pin("tabA", url="https://example.invalid/KEY-1")
        state.set_pin_scope("jira", "KEY-1", "global", "tabA")
        state.set_pin_scope("jira", "KEY-1", "tab", "tabB")
        pin = state.get_pins("tabB")[0]
        assert pin["meta"] == {"url": "https://example.invalid/KEY-1"}
        assert pin["label"] == "Epic"

    def test_unknown_pin_reports_not_moved(self):
        assert state.set_pin_scope("jira", "NOPE", "global", "tabA")["moved"] is False
        assert state.set_pin_scope("jira", "NOPE", "tab", "tabA")["moved"] is False

    def test_promote_is_idempotent(self):
        _pin("tabA")
        state.set_pin_scope("jira", "KEY-1", "global", "tabA")
        assert state.set_pin_scope("jira", "KEY-1", "global", "tabB")["moved"] is True
        assert list(state.pinned_contexts[state.GLOBAL_CONTEXT_ID]) == ["jira::KEY-1"]

    def test_include_global_false_returns_tab_pins_only(self):
        _pin("tabA", item_id="KEY-1")
        state.set_pin_scope("jira", "KEY-1", "global", "tabA")
        _pin("tabA", item_id="KEY-2", label="Local")
        assert [p["id"] for p in state.get_pins("tabA", include_global=False)] == ["KEY-2"]

    def test_remove_with_global_scope_deletes_everywhere(self):
        _pin("tabA")
        state.set_pin_scope("jira", "KEY-1", "global", "tabA")
        result = state.remove_pin("jira", "KEY-1", "tabB", scope="global")
        assert result["unpinned"] is True
        assert state.get_pins("tabA") == []
        assert state.get_pins("tabB") == []

    def test_remove_with_tab_scope_leaves_global_alone(self):
        _pin("tabA")
        state.set_pin_scope("jira", "KEY-1", "global", "tabA")
        result = state.remove_pin("jira", "KEY-1", "tabB")
        assert result["unpinned"] is False
        assert [p["id"] for p in state.get_pins("tabB")] == ["KEY-1"]

    def test_clearing_a_tab_leaves_global_pins(self):
        _pin("tabA")
        state.set_pin_scope("jira", "KEY-1", "global", "tabA")
        _pin("tabB", item_id="KEY-2", label="Local")
        state.clear_pins("tabB")
        assert [p["id"] for p in state.get_pins("tabB")] == ["KEY-1"]
