import json

import pytest

from marketplace import installer
from marketplace import state as skill_state
from marketplace.permissions import files_digest
from skills._sharing import bundle, destinations, messages, publisher
from skills._sharing.errors import ShareError


def _stored_doc(provider, folder, name):
    return json.loads(provider.files[(folder["folder_id"], name)][0])


def _skill_folder(provider, skill_id):
    root = provider.default_root()
    return provider.child_folder(root, skill_id, create=False)


def test_first_publish_writes_bundle_manifest_and_skill_json(provider, make_mine):
    skill_id = make_mine()
    out = publisher.publish(provider, skill_id, author="Mayuresh Kulkarni")

    assert out["version"] == 1
    assert out["reused"] is False
    folder = _skill_folder(provider, skill_id)
    v1 = provider.child_folder(folder, "v1", create=False)
    zip_bytes = provider.files[(v1["folder_id"], "bundle.zip")][0]
    manifest = _stored_doc(provider, v1, "manifest.json")
    assert manifest["bundle_sha256"] == bundle.bundle_sha256(zip_bytes)
    assert manifest["name"] == skill_id
    assert manifest["files_digest"] == out["digest"]
    doc = _stored_doc(provider, folder, "skill.json")
    assert doc["latest"] == 1
    assert doc["author"] == "Mayuresh Kulkarni"
    assert [v["version"] for v in doc["versions"]] == [1]
    assert messages.parse_share_link(out["link"]) == {"drive_id": "d1", "folder_id": folder["folder_id"]}


def test_first_publish_returns_the_share_message(provider, make_mine):
    out = publisher.publish(provider, make_mine(), author="Mayuresh Kulkarni")
    assert out["link"] in out["message"]
    assert "Mayuresh Kulkarni" in out["message"]
    assert "Weekly Report" in out["message"]


def test_reused_publish_returns_a_message_with_the_same_link(provider, make_mine):
    skill_id = make_mine()
    first = publisher.publish(provider, skill_id, author="Mayuresh Kulkarni")
    again = publisher.publish(provider, skill_id, author="Mayuresh Kulkarni")
    assert again["reused"] is True
    assert again["link"] == first["link"]
    assert first["link"] in again["message"]
    assert "Weekly Report" in again["message"]


def test_skill_json_is_written_last(provider, make_mine):
    publisher.publish(provider, make_mine(), author="A")
    assert [name for _folder, name in provider.writes] == ["bundle.zip", "manifest.json", "skill.json"]


def test_entry_records_the_share_state(provider, make_mine):
    skill_id = make_mine()
    out = publisher.publish(provider, skill_id, author="A")
    entry = skill_state.get_entry(skill_id)
    assert entry["tier"] == "Mine"
    assert entry["published_version"] == 1
    assert entry["published_digest"] == out["digest"]
    assert entry["share_source"] == {
        "drive_id": "d1",
        "folder_id": out["folder"]["folder_id"],
        "web_url": out["web_url"],
    }


def test_republishing_unchanged_content_reuses_the_version(provider, make_mine):
    skill_id = make_mine()
    publisher.publish(provider, skill_id, author="A")
    writes = list(provider.writes)
    again = publisher.publish(provider, skill_id, author="A")
    assert again["version"] == 1
    assert again["reused"] is True
    assert provider.writes == writes


def test_changed_content_publishes_a_new_version_and_keeps_the_old_one(provider, make_mine, skills_dir):
    skill_id = make_mine()
    first = publisher.publish(provider, skill_id, author="A")
    (skills_dir / "mine" / skill_id / "SKILL.md").write_text("---\nname: Weekly Report\n---\n\nChanged\n", encoding="utf-8")
    second = publisher.publish(provider, skill_id, author="A")

    assert second["version"] == 2
    assert second["digest"] != first["digest"]
    folder = _skill_folder(provider, skill_id)
    doc = _stored_doc(provider, folder, "skill.json")
    assert doc["latest"] == 2
    assert [v["version"] for v in doc["versions"]] == [1, 2]
    v1 = provider.child_folder(folder, "v1", create=False)
    assert (v1["folder_id"], "bundle.zip") in provider.files
    assert skill_state.get_entry(skill_id)["published_version"] == 2


def test_the_destination_is_fixed_after_the_first_publish(provider, make_mine, skills_dir):
    skill_id = make_mine()
    first = publisher.publish(provider, skill_id, author="A")
    (skills_dir / "mine" / skill_id / "SKILL.md").write_text("---\nname: Weekly Report\n---\n\nChanged\n", encoding="utf-8")
    elsewhere = provider.child_folder(provider.default_root(), "Elsewhere")
    second = publisher.publish(provider, skill_id, author="A", root=elsewhere)
    assert second["folder"]["folder_id"] == first["folder"]["folder_id"]


def test_a_chosen_root_is_used_on_the_first_publish(provider, make_mine):
    chosen = provider.child_folder(provider.default_root(), "Team Skills")
    skill_id = make_mine()
    out = publisher.publish(provider, skill_id, author="A", root=chosen)
    assert provider.child_folder(chosen, skill_id, create=False)["folder_id"] == out["folder"]["folder_id"]


@pytest.mark.parametrize("name", ["a" * 65, "mine"])
def test_a_name_the_receiver_would_refuse_is_not_published(provider, make_mine, name):
    skill_id = make_mine(name)
    assert skill_id == name
    with pytest.raises(ShareError) as err:
        publisher.publish(provider, skill_id, author="A", people=["bob@example.com"])
    assert err.value.code == "invalid"
    assert "64" in err.value.message
    assert provider.writes == []
    assert provider.folders == {}
    assert provider.grants == []


def test_a_64_character_name_still_publishes(provider, make_mine):
    skill_id = make_mine("a" * 64)
    out = publisher.publish(provider, skill_id, author="A")
    assert out["version"] == 1


def test_only_mine_skills_can_be_published(provider, skills_dir):
    installer.save_installed([{"id": "someone-elses", "tier": "Community", "version": "1"}])
    with pytest.raises(ShareError) as err:
        publisher.publish(provider, "someone-elses", author="A")
    assert err.value.code == "not_mine"
    with pytest.raises(ShareError) as err:
        publisher.publish(provider, "does-not-exist", author="A")
    assert err.value.code == "not_mine"


def test_a_failed_skill_json_write_leaves_the_entry_alone_and_a_retry_succeeds(provider, make_mine):
    skill_id = make_mine()
    provider.fail_on["write_json_create"] = ShareError("forbidden", "no")
    with pytest.raises(ShareError):
        publisher.publish(provider, skill_id, author="A")
    assert "share_source" not in skill_state.get_entry(skill_id)
    out = publisher.publish(provider, skill_id, author="A")
    assert out["version"] == 1
    assert skill_state.get_entry(skill_id)["published_version"] == 1


def test_a_concurrent_edit_of_skill_json_is_a_conflict(provider, make_mine, skills_dir):
    skill_id = make_mine()
    publisher.publish(provider, skill_id, author="A")
    (skills_dir / "mine" / skill_id / "SKILL.md").write_text("---\nname: Weekly Report\n---\n\nChanged\n", encoding="utf-8")
    provider.fail_on["write_json_replace"] = ShareError("conflict", "changed")
    with pytest.raises(ShareError) as err:
        publisher.publish(provider, skill_id, author="A")
    assert err.value.code == "conflict"
    assert skill_state.get_entry(skill_id)["published_version"] == 1


def test_people_are_granted_read_on_the_skill_folder(provider, make_mine):
    out = publisher.publish(provider, make_mine(), author="A", people=["a@contoso.com", "b@contoso.com"])
    assert provider.grants == [(out["folder"]["folder_id"], ["a@contoso.com", "b@contoso.com"])]


def test_no_people_means_no_grant(provider, make_mine):
    publisher.publish(provider, make_mine(), author="A")
    assert provider.grants == []


def test_a_damaged_skill_json_is_refused(provider, make_mine):
    skill_id = make_mine()
    out = publisher.publish(provider, skill_id, author="A")
    provider.files[(out["folder"]["folder_id"], "skill.json")] = (b'{"latest": "two"}', '"e9"')
    with pytest.raises(ShareError) as err:
        publisher.publish(provider, skill_id, author="A")
    assert err.value.code == "invalid"


def test_published_files_digest_matches_the_local_files(provider, make_mine, skills_dir):
    skill_id = make_mine(extra={"notes/ref.md": b"ref"})
    out = publisher.publish(provider, skill_id, author="A")
    local = bundle.read_skill_dir(skills_dir / "mine" / skill_id)
    assert out["digest"] == files_digest(local)


def test_an_address_that_cannot_be_granted_does_not_fail_the_share(provider, make_mine):
    skill_id = make_mine()
    provider.ungrantable.add("outside@gmail.com")
    out = publisher.publish(provider, skill_id, author="A", people=["a@contoso.com", "outside@gmail.com"])

    assert out["ungranted"] == ["outside@gmail.com"]
    assert out["link"]
    assert out["version"] == 1
    assert provider.grants == [(out["folder"]["folder_id"], ["a@contoso.com"])]
    assert skill_state.get_entry(skill_id)["published_version"] == 1


def test_publish_with_everyone_granted_reports_nobody_ungranted(provider, make_mine):
    out = publisher.publish(provider, make_mine(), author="A", people=["a@contoso.com"])
    assert out["ungranted"] == []


def test_a_failed_invite_still_records_the_share_state(provider, make_mine):
    skill_id = make_mine()
    provider.fail_on["grant_read"] = ShareError("forbidden", "no access")
    with pytest.raises(ShareError) as err:
        publisher.publish(provider, skill_id, author="A", people=["a@contoso.com"])
    assert err.value.code == "policy_blocked"

    entry = skill_state.get_entry(skill_id)
    assert entry["share_source"]["folder_id"]
    assert entry["published_version"] == 1
    assert entry["published_digest"]


def test_retry_after_a_failed_invite_reuses_the_same_folder_even_with_a_different_root(provider, make_mine):
    skill_id = make_mine()
    provider.fail_on["grant_read"] = ShareError("forbidden", "no access")
    with pytest.raises(ShareError):
        publisher.publish(provider, skill_id, author="A", people=["a@contoso.com"])
    share_source = dict(skill_state.get_entry(skill_id)["share_source"])
    other_root = provider.child_folder(provider.default_root(), "Elsewhere")
    folders_before = len(provider.folders)

    out = publisher.publish(provider, skill_id, author="A", root=other_root, people=["a@contoso.com"])

    assert out["reused"] is True
    assert out["version"] == 1
    assert len(provider.folders) == folders_before
    assert skill_state.get_entry(skill_id)["share_source"] == share_source
    assert provider.grants == [(share_source["folder_id"], ["a@contoso.com"])]


def _delete_folder(provider, folder_id):
    for key in [k for k, f in provider.folders.items() if f["folder_id"] == folder_id]:
        del provider.folders[key]


def test_a_deleted_skill_folder_is_recreated_at_the_default_and_the_link_is_replaced(provider, make_mine):
    skill_id = make_mine()
    first = publisher.publish(provider, skill_id, author="A")
    assert first["relinked"] is False
    _delete_folder(provider, first["folder"]["folder_id"])

    out = publisher.publish(provider, skill_id, author="A")

    assert out["relinked"] is True
    assert out["version"] == 1
    assert out["reused"] is False
    assert out["folder"]["folder_id"] != first["folder"]["folder_id"]
    assert out["link"] != first["link"]
    assert (out["folder"]["folder_id"], "skill.json") in provider.files
    assert skill_state.get_entry(skill_id)["share_source"]["folder_id"] == out["folder"]["folder_id"]


def test_a_deleted_skill_folder_honours_the_folder_chosen_in_the_dialog(provider, make_mine):
    skill_id = make_mine()
    first = publisher.publish(provider, skill_id, author="A")
    _delete_folder(provider, first["folder"]["folder_id"])
    chosen = _chosen(provider)

    out = publisher.publish(provider, skill_id, author="A", root=chosen)

    assert out["relinked"] is True
    assert out["saved_path"][-2:] == ["Team Skills", skill_id]


def test_a_deleted_root_folder_is_recreated(provider, make_mine):
    skill_id = make_mine()
    first = publisher.publish(provider, skill_id, author="A")
    provider.folders.clear()

    out = publisher.publish(provider, skill_id, author="A")

    assert out["relinked"] is True
    assert out["saved_path"][-2:] == ["AI Gator Skills", skill_id]
    assert out["folder"]["folder_id"] != first["folder"]["folder_id"]


def test_a_deleted_folder_still_asks_for_the_audience_of_a_shared_destination(provider, make_mine):
    skill_id = make_mine()
    first = publisher.publish(provider, skill_id, author="A")
    _delete_folder(provider, first["folder"]["folder_id"])
    chosen = _chosen(provider)
    provider.audiences[chosen["folder_id"]] = {"kind": "org", "name": "Your organization", "approx_count": None}

    with pytest.raises(ShareError) as err:
        publisher.publish(provider, skill_id, author="A", root=chosen)

    assert err.value.code == "audience_unacknowledged"


def _chosen(provider, name="Team Skills"):
    return provider.child_folder(provider.default_root(), name)


def test_an_upload_refusal_is_a_policy_block_and_nothing_is_recorded(provider, make_mine):
    skill_id = make_mine()
    provider.fail_on["write_file"] = ShareError("forbidden", "label")
    with pytest.raises(ShareError) as err:
        publisher.publish(provider, skill_id, author="A", people=["a@contoso.com"])
    assert err.value.code == "policy_blocked"
    assert "Nothing was shared" in err.value.message
    assert "share_source" not in skill_state.get_entry(skill_id)
    assert not any(name == "skill.json" for _, name in provider.writes)
    assert provider.grants == []


def test_a_refused_skill_folder_stays_forbidden(provider, make_mine):
    skill_id = make_mine()
    chosen = _chosen(provider)
    original = provider.child_folder

    def deny(parent, name, create=True):
        if name == skill_id:
            raise ShareError("forbidden", "no write access")
        return original(parent, name, create)

    provider.child_folder = deny
    with pytest.raises(ShareError) as err:
        publisher.publish(provider, skill_id, author="A", root=chosen)
    assert err.value.code == "forbidden"


def test_an_invite_refusal_is_a_policy_block_that_names_the_saved_skill(provider, make_mine):
    provider.fail_on["grant_read"] = ShareError("forbidden", "no sharing")
    with pytest.raises(ShareError) as err:
        publisher.publish(provider, make_mine(), author="A", people=["a@contoso.com"])
    assert err.value.code == "policy_blocked"
    assert "was saved" in err.value.message


def test_a_non_forbidden_error_keeps_its_code(provider, make_mine):
    provider.fail_on["write_file"] = ShareError("throttled", "slow down")
    with pytest.raises(ShareError) as err:
        publisher.publish(provider, make_mine(), author="A")
    assert err.value.code == "throttled"


def test_a_chosen_root_reports_where_it_was_saved_and_is_remembered(provider, make_mine):
    chosen = _chosen(provider)
    skill_id = make_mine()
    out = publisher.publish(provider, skill_id, author="A", root=chosen)
    assert out["saved_path"] == ["OneDrive", "AI Gator Skills", "Team Skills", skill_id]
    assert out["audience"]["kind"] == "private"
    recent = destinations.load_recent()
    assert [r["folder_id"] for r in recent] == [chosen["folder_id"]]


def test_the_default_location_is_not_remembered(provider, make_mine):
    out = publisher.publish(provider, make_mine(), author="A")
    assert out["saved_path"] == ["OneDrive", "AI Gator Skills", "weekly-report"]
    assert destinations.load_recent() == []


def test_a_shared_folder_needs_the_audience_acknowledged(provider, make_mine):
    chosen = _chosen(provider)
    provider.audiences[chosen["folder_id"]] = {"kind": "folder", "name": "Team Skills", "approx_count": 4}
    skill_id = make_mine()
    with pytest.raises(ShareError) as err:
        publisher.publish(provider, skill_id, author="A", root=chosen)
    assert err.value.code == "audience_unacknowledged"
    assert provider.writes == []
    assert provider.child_folder(chosen, skill_id, create=False) is None

    out = publisher.publish(provider, skill_id, author="A", root=chosen, audience_ack=True)
    assert out["audience"]["kind"] == "folder"
    assert out["version"] == 1


def test_an_existing_destination_is_not_vetted_again(provider, make_mine, skills_dir):
    skill_id = make_mine()
    first = publisher.publish(provider, skill_id, author="A")
    wide = _chosen(provider, "Wide")
    provider.audiences[wide["folder_id"]] = {"kind": "org", "name": "Your organization", "approx_count": None}
    (skills_dir / "mine" / skill_id / "SKILL.md").write_text("---\nname: Weekly Report\n---\n\nChanged\n", encoding="utf-8")
    out = publisher.publish(provider, skill_id, author="A", root=wide)
    assert out["folder"]["folder_id"] == first["folder"]["folder_id"]
    assert out["audience"] is None
    assert out["saved_path"] == ["OneDrive", "AI Gator Skills", skill_id]


def test_a_skill_by_someone_else_in_the_chosen_folder_is_not_touched(provider, make_mine):
    chosen = _chosen(provider)
    skill_id = make_mine()
    theirs = provider.child_folder(chosen, skill_id)
    provider.files[(theirs["folder_id"], "skill.json")] = (
        json.dumps({"latest": 1, "versions": [], "author": "Bob"}).encode(),
        '"e1"',
    )
    folders_before, writes_before = dict(provider.folders), list(provider.writes)
    with pytest.raises(ShareError) as err:
        publisher.publish(provider, skill_id, author="Ann", root=chosen)
    assert err.value.code == "not_yours"
    assert "Bob" in err.value.message
    assert provider.folders == folders_before
    assert provider.writes == writes_before


def test_my_own_skill_in_the_chosen_folder_gets_a_new_version(provider, make_mine, skills_dir):
    chosen = _chosen(provider)
    skill_id = make_mine()
    publisher.publish(provider, skill_id, author="Ann", root=chosen)
    entry = skill_state.get_entry(skill_id)
    skill_state.update_entry(skill_id, {"share_source": None})
    (skills_dir / "mine" / skill_id / "SKILL.md").write_text("---\nname: Weekly Report\n---\n\nChanged\n", encoding="utf-8")
    out = publisher.publish(provider, skill_id, author="ann", root=chosen)
    assert out["version"] == 2
    assert entry["share_source"]["folder_id"] == out["folder"]["folder_id"]


@pytest.mark.parametrize("code", ["not_found", "invalid"])
def test_a_missing_or_file_root_is_refused_before_anything_is_written(provider, make_mine, code):
    skill_id = make_mine()
    root = {"drive_id": "d1", "folder_id": "nope", "web_url": "", "name": "x"}
    if code == "invalid":
        root = _chosen(provider)
        provider.not_folders.add(root["folder_id"])
    with pytest.raises(ShareError) as err:
        publisher.publish(provider, skill_id, author="A", root=root)
    assert err.value.code == code
    assert provider.writes == []


def test_sharing_with_nobody_still_publishes(provider, make_mine):
    out = publisher.publish(provider, make_mine(), author="A", people=[])
    assert out["ungranted"] == []
    assert provider.grants == []
