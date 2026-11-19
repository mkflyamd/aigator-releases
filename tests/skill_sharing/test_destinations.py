import json

import pytest

from marketplace import installer
from marketplace import state as skill_state
from skills._sharing import destinations, publisher
from skills._sharing.errors import ShareError


def _loc(n):
    return {"drive_id": "d1", "folder_id": f"f{n}", "name": f"F{n}", "path": ["OneDrive", f"F{n}"], "web_url": f"https://x/{n}"}


def test_the_default_is_a_placeholder_until_the_first_publish_creates_it(provider, skills_dir):
    out = destinations.locations(provider, "weekly-report")
    assert out["default"] == {
        "drive_id": "d1",
        "folder_id": "",
        "name": "AI Gator Skills",
        "path": ["OneDrive", "AI Gator Skills"],
        "web_url": "",
    }
    assert provider.folders == {}


def test_the_default_is_described_once_it_exists(provider, skills_dir):
    provider.default_root()
    default = destinations.locations(provider, "weekly-report")["default"]
    assert default["folder_id"]
    assert default["path"] == ["OneDrive", "AI Gator Skills"]


def test_recent_locations_are_newest_first_and_deduplicated(skills_dir):
    for n in (1, 2, 3, 2):
        destinations.remember(_loc(n))
    assert [r["folder_id"] for r in destinations.load_recent()] == ["f2", "f3", "f1"]


def test_only_the_five_newest_recents_are_kept(skills_dir):
    for n in range(8):
        destinations.remember(_loc(n))
    assert [r["folder_id"] for r in destinations.load_recent()] == ["f7", "f6", "f5", "f4", "f3"]


def test_a_corrupt_recents_file_is_treated_as_empty_and_replaced(skills_dir):
    (skills_dir / "share-locations.json").write_text("{not json", encoding="utf-8")
    assert destinations.load_recent() == []
    destinations.remember(_loc(1))
    assert len(destinations.load_recent()) == 1


def test_recents_entries_missing_fields_are_dropped(skills_dir):
    (skills_dir / "share-locations.json").write_text(json.dumps([{"drive_id": "d1"}, _loc(1), "junk"]), encoding="utf-8")
    assert [r["folder_id"] for r in destinations.load_recent()] == ["f1"]


def test_the_current_destination_comes_from_the_published_skill(provider, make_mine):
    skill_id = make_mine()
    published = publisher.publish(provider, skill_id, author="A")
    out = destinations.locations(provider, skill_id)
    assert out["current"]["folder_id"] == published["folder"]["folder_id"]


def test_there_is_no_current_destination_before_publishing_or_when_it_is_gone(provider, make_mine):
    skill_id = make_mine()
    assert destinations.locations(provider, skill_id)["current"] is None
    skill_state.update_entry(skill_id, {"share_source": {"drive_id": "d1", "folder_id": "gone", "web_url": ""}})
    assert destinations.locations(provider, skill_id)["current"] is None


def test_check_with_no_ids_checks_the_default_folder(provider, skills_dir):
    out = destinations.check(provider, "weekly-report", "", "", "A")
    assert out["ok"] is True
    assert out["can_write"] is True
    assert out["audience"]["kind"] == "private"
    assert out["existing"] is None
    assert out["location"]["path"] == ["OneDrive", "AI Gator Skills"]


def test_check_reports_a_missing_folder(provider, skills_dir):
    out = destinations.check(provider, "weekly-report", "d1", "nope", "A")
    assert out == {"ok": False, "reason": "not_found", "can_write": None, "location": None, "audience": None, "existing": None}


def test_check_reports_a_file_as_not_a_folder(provider, skills_dir):
    chosen = provider.child_folder(provider.default_root(), "X")
    provider.not_folders.add(chosen["folder_id"])
    out = destinations.check(provider, "weekly-report", "d1", chosen["folder_id"], "A")
    assert out["ok"] is False
    assert out["reason"] == "not_a_folder"


def test_check_lets_other_errors_through(provider, skills_dir):
    provider.describe_folder = lambda d, f: (_ for _ in ()).throw(ShareError("throttled", "slow"))
    with pytest.raises(ShareError) as err:
        destinations.check(provider, "weekly-report", "d1", "f1", "A")
    assert err.value.code == "throttled"


def test_write_access_is_known_on_my_own_drive_and_unknown_elsewhere(provider, skills_dir):
    chosen = provider.child_folder(provider.default_root(), "X")
    assert destinations.check(provider, "s", "d1", chosen["folder_id"], "A")["can_write"] is True
    provider.my_drive_id = lambda: "other"
    assert destinations.check(provider, "s", "d1", chosen["folder_id"], "A")["can_write"] is None


def test_check_passes_the_audience_through(provider, skills_dir):
    chosen = provider.child_folder(provider.default_root(), "X")
    provider.audiences[chosen["folder_id"]] = {"kind": "org", "name": "Your organization", "approx_count": None}
    assert destinations.check(provider, "s", "d1", chosen["folder_id"], "A")["audience"]["kind"] == "org"


def test_check_flags_a_skill_already_there_as_mine_or_not(provider, make_mine):
    chosen = provider.child_folder(provider.default_root(), "X")
    skill_id = make_mine()
    publisher.publish(provider, skill_id, author="Ann", root=chosen)
    mine = destinations.check(provider, skill_id, "d1", chosen["folder_id"], " ann ")["existing"]
    assert mine["yours"] is True
    assert mine["version"] == 1
    assert mine["author"] == "Ann"
    theirs = destinations.check(provider, skill_id, "d1", chosen["folder_id"], "Bob")["existing"]
    assert theirs["yours"] is False
    assert destinations.check(provider, skill_id, "d1", chosen["folder_id"], "")["existing"]["yours"] is False


def test_check_finds_nothing_when_the_folder_has_no_such_skill(provider, skills_dir):
    chosen = provider.child_folder(provider.default_root(), "X")
    assert destinations.check(provider, "other-skill", "d1", chosen["folder_id"], "A")["existing"] is None
