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


def test_review_of_an_oversize_bundle_is_too_large(provider, make_mine):
    _skill_id, out = _published(provider, make_mine)
    key = (_version_folder(provider, out)["folder_id"], "bundle.zip")
    provider.files[key] = (b"x" * (receiver.MAX_BUNDLE_BYTES + 1), '"big"')
    with pytest.raises(ShareError) as err:
        receiver.review(provider, _ref(out))
    assert err.value.code == "too_large"


def test_review_of_an_oversize_manifest_is_too_large(provider, make_mine):
    _skill_id, out = _published(provider, make_mine)
    key = (_version_folder(provider, out)["folder_id"], "manifest.json")
    provider.files[key] = (b" " * (receiver.MAX_JSON_BYTES + 1), '"big"')
    with pytest.raises(ShareError) as err:
        receiver.review(provider, _ref(out))
    assert err.value.code == "too_large"


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


def _edit_skill_json(provider, out, edit):
    key = (out["folder"]["folder_id"], "skill.json")
    doc = json.loads(provider.files[key][0])
    edit(doc)
    provider.files[key] = (json.dumps(doc).encode(), '"edited"')


def test_a_manifest_digest_that_differs_from_skill_json_is_tampered_on_review(provider, make_mine):
    _skill_id, out = _published(provider, make_mine)
    _edit_skill_json(provider, out, lambda doc: doc["versions"][0].update(files_digest="0" * 64))
    with pytest.raises(ShareError) as err:
        receiver.review(provider, _ref(out))
    assert err.value.code == "tampered"


def test_a_manifest_digest_that_differs_from_skill_json_is_tampered_on_install(provider, make_mine, skills_dir):
    _skill_id, out = _published(provider, make_mine)
    _recipient(skills_dir)
    _edit_skill_json(provider, out, lambda doc: doc["versions"][0].update(files_digest="0" * 64))
    with pytest.raises(ShareError) as err:
        receiver.install(provider, _ref(out), version=1, digest=out["digest"])
    assert err.value.code == "tampered"
    assert installer.load_installed() == []


@pytest.mark.parametrize("action", ["review", "install"])
def test_a_version_list_without_the_wanted_version_is_invalid(provider, make_mine, skills_dir, action):
    _skill_id, out = _published(provider, make_mine)
    _recipient(skills_dir)
    _edit_skill_json(provider, out, lambda doc: doc.update(versions=[]))
    with pytest.raises(ShareError) as err:
        if action == "review":
            receiver.review(provider, _ref(out))
        else:
            receiver.install(provider, _ref(out), version=1, digest=out["digest"])
    assert err.value.code == "invalid"


def test_two_installs_of_one_name_are_serialized_and_leave_one_entry(provider, make_mine, skills_dir):
    import threading

    _skill_id, out = _published(provider, make_mine)
    _recipient(skills_dir)
    reviewed = receiver.review(provider, _ref(out))
    real_existing = receiver._existing
    both_checked = threading.Barrier(2, timeout=0.5)
    results = []
    never_met = []

    def slow_existing(skill_id, ref):
        found = real_existing(skill_id, ref)
        try:
            both_checked.wait()
        except threading.BrokenBarrierError:
            never_met.append(1)
        return found

    def go():
        try:
            receiver.install(provider, _ref(out), version=1, digest=reviewed["digest"])
            results.append("installed")
        except ShareError as err:
            results.append(err.code)

    receiver._existing = slow_existing
    try:
        threads = [threading.Thread(target=go) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        receiver._existing = real_existing
    assert never_met == [1, 1]
    assert results == ["installed", "installed"]
    assert len(installer.load_installed()) == 1


def _second_share(provider, out):
    """The same skill name published to a different shared folder, so it counts as another source."""
    other = provider._folder("another-owner", "Weekly Report", True)
    other_v1 = provider.child_folder(other, "v1")
    source_v1 = _version_folder(provider, out)
    for source, target in ((out["folder"], other), (source_v1, other_v1)):
        for (folder_id, name), value in list(provider.files.items()):
            if folder_id == source["folder_id"]:
                provider.files[(target["folder_id"], name)] = value
    return {"drive_id": other["drive_id"], "folder_id": other["folder_id"]}


def test_install_never_replaces_a_skill_installed_from_another_share(provider, make_mine, skills_dir):
    skill_id, out = _published(provider, make_mine)
    _recipient(skills_dir)
    receiver.install(provider, _ref(out), version=1, digest=out["digest"])
    before_file = (skills_dir / skill_id / "SKILL.md").read_bytes()
    before_entry = dict(skill_state.get_entry(skill_id))
    other = _second_share(provider, out)

    with pytest.raises(ShareError) as err:
        receiver.install(provider, other, version=1, digest=out["digest"])

    assert err.value.code == "collision"
    assert (skills_dir / skill_id / "SKILL.md").read_bytes() == before_file
    assert skill_state.get_entry(skill_id) == before_entry
    assert len(installer.load_installed()) == 1


def test_install_never_replaces_a_built_in_skill(provider, make_mine, skills_dir):
    _skill_id, out = _published(provider, make_mine, name="Email")
    _recipient(skills_dir)

    with pytest.raises(ShareError) as err:
        receiver.install(provider, _ref(out), version=1, digest=out["digest"])

    assert err.value.code == "collision"
    assert installer.load_installed() == []


def test_two_installs_of_one_name_from_different_shares_let_exactly_one_win(provider, make_mine, skills_dir):
    import threading

    skill_id, out = _published(provider, make_mine)
    _recipient(skills_dir)
    refs = [_ref(out), _second_share(provider, out)]
    results = []

    def go(ref):
        try:
            receiver.install(provider, ref, version=1, digest=out["digest"])
            results.append("installed")
        except ShareError as err:
            results.append(err.code)

    real_existing = receiver._existing
    both_checked = threading.Barrier(2, timeout=0.5)

    def slow_existing(name, ref):
        found = real_existing(name, ref)
        try:
            both_checked.wait()
        except threading.BrokenBarrierError:
            pass
        return found

    receiver._existing = slow_existing
    try:
        threads = [threading.Thread(target=go, args=(ref,)) for ref in refs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        receiver._existing = real_existing

    assert sorted(results) == ["collision", "installed"]
    assert len(installer.load_installed()) == 1
    assert skill_state.get_entry(skill_id)["share_source"] in [
        {"drive_id": ref["drive_id"], "folder_id": ref["folder_id"]} for ref in refs
    ]
