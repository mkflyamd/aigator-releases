import json

import pytest

from marketplace import installer
from marketplace import state as skill_state
from marketplace.permissions import files_digest
from skills._sharing import bundle, messages, publisher
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
    assert err.value.code == "forbidden"

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
