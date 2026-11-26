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
    provider.fail_on["write_file_create"] = ShareError("forbidden", "label")
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
    provider.fail_on["write_file_create"] = ShareError("throttled", "slow down")
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


def test_a_saved_destination_is_used_and_a_different_chosen_folder_is_ignored(provider, make_mine, skills_dir):
    skill_id = make_mine()
    first = publisher.publish(provider, skill_id, author="A")
    wide = _chosen(provider, "Wide")
    provider.audiences[wide["folder_id"]] = {"kind": "org", "name": "Your organization", "approx_count": None}
    (skills_dir / "mine" / skill_id / "SKILL.md").write_text("---\nname: Weekly Report\n---\n\nChanged\n", encoding="utf-8")
    out = publisher.publish(provider, skill_id, author="A", root=wide)
    assert out["folder"]["folder_id"] == first["folder"]["folder_id"]
    assert out["audience"]["kind"] == "private"
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


def test_concurrent_publishes_of_one_skill_are_serialised(provider, make_mine):
    import threading
    import time

    skill_id = make_mine()
    real_read_json = provider.read_json

    def slow_read_json(folder, name, max_bytes=None):
        found = real_read_json(folder, name, max_bytes)
        time.sleep(0.05)  # widen the window between reading skill.json and writing the version
        return found

    provider.read_json = slow_read_json
    results, errors = [], []

    def run():
        try:
            results.append(publisher.publish(provider, skill_id, author="A"))
        except ShareError as err:  # only reached when the per-skill lock fails
            errors.append(err)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert sorted(r["reused"] for r in results) == [False, True]
    assert {r["version"] for r in results} == {1}
    assert [name for _folder, name in provider.writes].count("bundle.zip") == 1


def test_publish_never_overwrites_an_existing_version_folder(provider, make_mine):
    skill_id = make_mine()
    folder = provider.child_folder(provider.default_root(), skill_id)
    v1 = provider.child_folder(folder, "v1")
    provider.write_file_create(v1, "bundle.zip", b"someone else's bundle")

    out = publisher.publish(provider, skill_id, author="A")

    assert out["version"] == 2
    assert provider.files[(v1["folder_id"], "bundle.zip")][0] == b"someone else's bundle"
    assert (v1["folder_id"], "manifest.json") not in provider.files
    assert [v["version"] for v in _stored_doc(provider, folder, "skill.json")["versions"]] == [2]


def test_publish_gives_up_when_every_version_number_is_taken(provider, make_mine):
    skill_id = make_mine()
    folder = provider.child_folder(provider.default_root(), skill_id)
    for n in range(1, 6):
        provider.write_file_create(provider.child_folder(folder, f"v{n}"), "bundle.zip", b"taken")

    with pytest.raises(ShareError) as err:
        publisher.publish(provider, skill_id, author="A")

    assert err.value.code == "conflict"
    assert (folder["folder_id"], "skill.json") not in provider.files


CHANGED_SKILL_MD = "---\nname: Weekly Report\n---\n\nChanged\n"


def test_stale_skill_json_fails_with_a_conflict_and_is_not_overwritten(provider, make_mine, skills_dir):
    skill_id = make_mine()
    publisher.publish(provider, skill_id, author="A")
    (skills_dir / "mine" / skill_id / "SKILL.md").write_text(CHANGED_SKILL_MD, encoding="utf-8")
    folder = _skill_folder(provider, skill_id)
    real_read_json = provider.read_json

    def read_then_lose_the_race(f, name, max_bytes=None):
        found = real_read_json(f, name, max_bytes)
        if name == "skill.json":
            other = {"schema": 1, "latest": 1, "versions": [], "by": "other"}
            provider._put(f, "skill.json", json.dumps(other).encode())
        return found

    provider.read_json = read_then_lose_the_race

    with pytest.raises(ShareError) as err:
        publisher.publish(provider, skill_id, author="A")

    assert err.value.code == "conflict"
    assert _stored_doc(provider, folder, "skill.json")["by"] == "other"


def _publish_as_me(provider, skill_id, **kw):
    return publisher.publish(provider, skill_id, author="A", **kw)


def test_the_default_folder_audience_is_checked_not_assumed(provider, make_mine):
    root = provider.default_root()
    provider.audiences[root["folder_id"]] = {"kind": "anyone", "name": "Anyone with the link", "approx_count": None}
    skill_id = make_mine()
    with pytest.raises(ShareError) as err:
        _publish_as_me(provider, skill_id)
    assert err.value.code == "audience_unacknowledged"
    assert "Anyone with the link" in err.value.message
    assert provider.writes == []
    out = _publish_as_me(provider, skill_id, audience_ack=True)
    assert out["audience"]["kind"] == "anyone"


def test_a_saved_skill_folder_is_rechecked_on_every_publish(provider, make_mine):
    skill_id = make_mine()
    first = _publish_as_me(provider, skill_id)
    provider.audiences[first["folder"]["folder_id"]] = {"kind": "org", "name": "Your organization", "approx_count": None}
    provider.writes.clear()
    with pytest.raises(ShareError) as err:
        _publish_as_me(provider, skill_id)
    assert err.value.code == "audience_unacknowledged"
    assert provider.writes == []
    again = _publish_as_me(provider, skill_id, audience_ack=True)
    assert again["skill_id"] == skill_id


def test_a_display_name_match_cannot_take_over_someone_elses_skill(provider, make_mine):
    chosen = provider.child_folder(provider.default_root(), "Team")
    skill_id = make_mine()
    _publish_as_me(provider, skill_id, root=chosen)
    provider.user_id = "u-impostor"
    provider.writes.clear()
    with pytest.raises(ShareError) as err:
        _publish_as_me(provider, skill_id, root=chosen)
    assert err.value.code == "not_yours"
    assert provider.writes == []


def test_a_saved_link_to_someone_elses_skill_is_refused(provider, make_mine):
    skill_id = make_mine()
    _publish_as_me(provider, skill_id)
    provider.user_id = "u-impostor"
    provider.writes.clear()
    with pytest.raises(ShareError) as err:
        _publish_as_me(provider, skill_id)
    assert err.value.code == "not_yours"
    assert provider.writes == []


def test_the_owner_id_is_recorded_in_skill_json(provider, make_mine):
    out = _publish_as_me(provider, make_mine())
    doc = json.loads(provider.files[(out["folder"]["folder_id"], "skill.json")][0])
    assert doc["author_id"] == "u-me"


def test_publish_refuses_when_the_user_identity_is_unknown(provider, make_mine):
    provider.user_id = ""
    with pytest.raises(ShareError):
        _publish_as_me(provider, make_mine())
    assert provider.writes == []


def test_publish_is_bound_to_the_file_list_the_user_reviewed(provider, make_mine):
    skill_id = make_mine()
    reviewed = publisher.inventory(skill_id)["inventory_digest"]
    out = _publish_as_me(provider, skill_id, inventory_digest=reviewed)
    assert out["digest"] == reviewed
    (publisher.installer.INSTALLED_SKILLS_DIR / "mine" / skill_id / "notes.md").write_text("added later")
    provider.writes.clear()
    with pytest.raises(ShareError) as err:
        _publish_as_me(provider, skill_id, inventory_digest=reviewed)
    assert err.value.code == "content_changed"
    assert provider.writes == []
