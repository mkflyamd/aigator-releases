import json
import shutil

import pytest

from marketplace import installer
from marketplace import state as skill_state
from sandbox import policy as _policy
from skills._sharing import messages, publisher, receiver
from skills._sharing.errors import ShareError


def _published(provider, make_mine, name="Weekly Report", **kwargs):
    skill_id = make_mine(name, **kwargs)
    return skill_id, publisher.publish(provider, skill_id, author="Mayuresh Kulkarni")


def _ref(out):
    return messages.parse_share_link(out["link"])


def _recipient(skills_dir):
    installer.save_installed([])
    shutil.rmtree(skills_dir / "mine")


def _version_folder(provider, out, version=1):
    return provider.child_folder(out["folder"], f"v{version}", create=False)


def _edit_manifest(provider, out, **changes):
    key = (_version_folder(provider, out)["folder_id"], "manifest.json")
    doc = json.loads(provider.files[key][0])
    doc.update(changes)
    provider.files[key] = (json.dumps(doc).encode(), '"edited"')


def test_review_returns_the_card_facts(provider, make_mine, skills_dir):
    skill_id, out = _published(provider, make_mine)
    _recipient(skills_dir)
    card = receiver.review(provider, _ref(out))

    assert card["skill_id"] == skill_id
    assert card["title"] == "Weekly Report"
    assert card["description"] == "Summarise the week"
    assert card["author"] == "Mayuresh Kulkarni"
    assert card["version"] == 1
    assert card["latest"] == 1
    assert card["digest"] == out["digest"]
    assert card["has_scripts"] is False
    assert card["requested_tools"] == {"filesystem": [], "network": [], "invalid": False}
    assert card["summary"]["digest"] == out["digest"]
    assert card["collision"] == ""


def test_review_writes_nothing(provider, make_mine, skills_dir):
    _skill_id, out = _published(provider, make_mine)
    _recipient(skills_dir)
    receiver.review(provider, _ref(out))
    assert installer.load_installed() == []
    assert not (skills_dir / "weekly-report").exists()


def test_review_defaults_to_the_latest_version_and_can_pick_an_older_one(provider, make_mine, skills_dir):
    skill_id, first = _published(provider, make_mine)
    (skills_dir / "mine" / skill_id / "SKILL.md").write_text("---\nname: Weekly Report\n---\n\nChanged\n", encoding="utf-8")
    second = publisher.publish(provider, skill_id, author="Mayuresh Kulkarni")
    _recipient(skills_dir)

    assert receiver.review(provider, _ref(second))["version"] == 2
    old = receiver.review(provider, _ref(second), version=1)
    assert old["version"] == 1
    assert old["latest"] == 2
    assert old["digest"] == first["digest"]


def test_review_recomputes_has_scripts_instead_of_trusting_the_manifest(provider, make_mine, skills_dir):
    _skill_id, out = _published(provider, make_mine, extra={"tools.py": b"x = 1\n"})
    _edit_manifest(provider, out, has_scripts=False, requested_tools={"filesystem": [], "network": [], "invalid": False})
    _recipient(skills_dir)
    assert receiver.review(provider, _ref(out))["has_scripts"] is True


def test_a_missing_skill_json_is_not_found(provider):
    with pytest.raises(ShareError) as err:
        receiver.review(provider, {"drive_id": "d1", "folder_id": "nothing-here"})
    assert err.value.code == "not_found"


def test_an_unknown_version_is_not_found(provider, make_mine):
    _skill_id, out = _published(provider, make_mine)
    for version in (0, 2, -1):
        with pytest.raises(ShareError) as err:
            receiver.review(provider, _ref(out), version=version)
        assert err.value.code == "not_found"


def test_an_incomplete_version_is_not_found(provider, make_mine):
    _skill_id, out = _published(provider, make_mine)
    del provider.files[(_version_folder(provider, out)["folder_id"], "bundle.zip")]
    with pytest.raises(ShareError) as err:
        receiver.review(provider, _ref(out))
    assert err.value.code == "not_found"


def test_a_modified_bundle_is_tampered(provider, make_mine):
    _skill_id, out = _published(provider, make_mine)
    key = (_version_folder(provider, out)["folder_id"], "bundle.zip")
    provider.files[key] = (provider.files[key][0] + b"x", '"edited"')
    with pytest.raises(ShareError) as err:
        receiver.review(provider, _ref(out))
    assert err.value.code == "tampered"


def test_a_manifest_digest_that_does_not_match_the_files_is_tampered(provider, make_mine):
    _skill_id, out = _published(provider, make_mine)
    _edit_manifest(provider, out, files_digest="0" * 64)
    with pytest.raises(ShareError) as err:
        receiver.review(provider, _ref(out))
    assert err.value.code == "tampered"


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "mine"},
        {"name": "../escape"},
        {"name": "Upper Case"},
        {"name": 7},
        {"schema": 2},
        {"version": 5},
        {"bundle_sha256": None},
    ],
)
def test_an_invalid_manifest_is_refused(provider, make_mine, changes):
    _skill_id, out = _published(provider, make_mine)
    _edit_manifest(provider, out, **changes)
    with pytest.raises(ShareError) as err:
        receiver.review(provider, _ref(out))
    assert err.value.code == "invalid"


def test_review_reports_a_name_collision(provider, make_mine, skills_dir):
    _skill_id, out = _published(provider, make_mine)
    assert receiver.review(provider, _ref(out))["collision"] == "mine"

    installer.save_installed([{"id": "weekly-report", "tier": "Community", "version": "1"}])
    assert receiver.review(provider, _ref(out))["collision"] == "installed"


def test_review_reports_a_collision_with_a_built_in_skill(provider, make_mine, skills_dir):
    _skill_id, out = _published(provider, make_mine, name="Email")
    _recipient(skills_dir)
    assert receiver.review(provider, _ref(out))["collision"] == "native"


def test_install_writes_the_skill_and_records_where_it_came_from(provider, make_mine, skills_dir):
    skill_id, out = _published(provider, make_mine)
    _recipient(skills_dir)

    result = receiver.install(provider, _ref(out), version=1, digest=out["digest"])

    assert result["ok"] is True
    assert result["skill_id"] == skill_id
    assert result["shared_by"] == "Mayuresh Kulkarni"
    assert (skills_dir / skill_id / "SKILL.md").is_file()
    entry = skill_state.get_entry(skill_id)
    assert entry["tier"] == "Community"
    assert entry["version"] == "1"
    assert entry["shared_version"] == 1
    assert entry["files_digest"] == out["digest"]
    assert entry["shared_by"] == "Mayuresh Kulkarni"
    assert entry["share_source"] == {"drive_id": "d1", "folder_id": out["folder"]["folder_id"]}
    assert "source" not in entry


def test_install_refuses_when_the_content_is_not_what_was_approved(provider, make_mine, skills_dir):
    _skill_id, out = _published(provider, make_mine)
    _recipient(skills_dir)
    with pytest.raises(ShareError) as err:
        receiver.install(provider, _ref(out), version=1, digest="0" * 64)
    assert err.value.code == "content_changed"
    assert installer.load_installed() == []
    assert not (skills_dir / "weekly-report").exists()


def test_install_refuses_a_tampered_bundle(provider, make_mine, skills_dir):
    _skill_id, out = _published(provider, make_mine)
    _recipient(skills_dir)
    key = (_version_folder(provider, out)["folder_id"], "bundle.zip")
    provider.files[key] = (provider.files[key][0] + b"x", '"edited"')
    with pytest.raises(ShareError) as err:
        receiver.install(provider, _ref(out), version=1, digest=out["digest"])
    assert err.value.code == "tampered"
    assert installer.load_installed() == []


def test_install_never_replaces_the_authors_own_skill(provider, make_mine, skills_dir):
    skill_id, out = _published(provider, make_mine)
    before = (skills_dir / "mine" / skill_id / "SKILL.md").read_bytes()
    with pytest.raises(ShareError) as err:
        receiver.install(provider, _ref(out), version=1, digest=out["digest"])
    assert err.value.code == "collision"
    assert (skills_dir / "mine" / skill_id / "SKILL.md").read_bytes() == before
    assert skill_state.get_entry(skill_id)["tier"] == "Mine"


def test_install_never_replaces_another_installed_skill(provider, make_mine, skills_dir):
    _skill_id, out = _published(provider, make_mine)
    _recipient(skills_dir)
    installer.save_installed([{"id": "weekly-report", "tier": "Community", "version": "9"}])
    with pytest.raises(ShareError) as err:
        receiver.install(provider, _ref(out), version=1, digest=out["digest"])
    assert err.value.code == "collision"
    assert skill_state.get_entry("weekly-report")["version"] == "9"


def test_install_passes_an_admin_block_through_as_the_installer_result(provider, make_mine, skills_dir, tmp_path):
    _skill_id, out = _published(provider, make_mine)
    _recipient(skills_dir)
    (tmp_path / "sandbox-policy.json").write_text(json.dumps({"approved_digests": []}), encoding="utf-8")
    _policy._reset_cache()

    result = receiver.install(provider, _ref(out), version=1, digest=out["digest"])

    assert result == {"ok": False, "error": "digest_not_approved", "digest": out["digest"]}
    assert installer.load_installed() == []
