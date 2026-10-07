import pytest

import config
from marketplace import installer, state
from marketplace.permissions import Permissions


@pytest.fixture(autouse=True)
def _index(tmp_path, monkeypatch):
    # installer binds these names at import time, so patch both modules.
    skills_dir = tmp_path / "installed-skills"
    plugins_dir = tmp_path / "plugins"
    for mod in (installer, config):
        monkeypatch.setattr(mod, "INSTALLED_SKILLS_DIR", skills_dir)
        monkeypatch.setattr(mod, "PLUGINS_DIR", plugins_dir)
    installer.save_installed([
        {"id": "solo", "version": "1.0", "tier": "community"},
        {"id": "bundle", "version": "2.0", "source": "mkt", "skill_ids": ["inner-a", "inner-b"]},
        {"id": "legacy", "version": "1.0"},
    ])


def test_disable_and_enable_round_trip_and_survive_reload():
    assert state.is_disabled("solo") is False
    assert state.set_disabled("solo", True) is True
    assert state.is_disabled("solo") is True
    assert state.get_entry("solo")["disabled"] is True
    assert state.set_disabled("solo", False) is True
    assert state.is_disabled("solo") is False
    assert "disabled" not in state.get_entry("solo")


def test_disabling_a_bundle_disables_its_skill_ids():
    state.set_disabled("bundle", True)
    assert state.disabled_ids() == {"bundle", "inner-a", "inner-b"}
    assert state.is_disabled("inner-a")


def test_unknown_skill_returns_false():
    assert state.set_disabled("nope", True) is False
    assert state.record_approval("nope", {}) is False


def test_record_approval_stores_permissions_and_clears_disabled():
    state.set_disabled("solo", True)
    perms = Permissions(filesystem=("~/x",), network=("h.example.com",))
    assert state.record_approval("solo", perms.to_dict()) is True
    entry = state.get_entry("solo")
    assert entry["permissions"] == perms.to_dict()
    assert entry["approved_at"]
    assert "disabled" not in entry
    assert state.approved_permissions("solo") == perms


def test_legacy_entry_has_no_grants():
    assert state.approved_permissions("legacy") == Permissions()
    assert state.approved_permissions("not-installed") == Permissions()


def test_bundle_inner_skill_uses_the_bundles_approval():
    perms = Permissions(network=("h.example.com",))
    state.record_approval("bundle", perms.to_dict())
    assert state.approved_permissions("inner-a") == perms


def test_skill_dir_for_matches_the_hook_folder_rules():
    assert state.skill_dir_for({"id": "solo"}) == config.INSTALLED_SKILLS_DIR / "solo"
    assert state.skill_dir_for({"id": "bundle", "source": "mkt", "version": "2.0"}) == (
        config.PLUGINS_DIR / "cache" / "mkt" / "bundle" / "2.0"
    )


def test_update_entry_none_deletes_a_key():
    state.update_entry("solo", {"note": "x"})
    assert state.get_entry("solo")["note"] == "x"
    state.update_entry("solo", {"note": None})
    assert "note" not in state.get_entry("solo")
