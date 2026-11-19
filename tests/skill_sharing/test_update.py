import json
import shutil
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from marketplace import installer
from marketplace import state as skill_state
from routes.skill_sharing import router
from skills._sharing import messages, publisher, receiver
from skills._sharing.errors import ShareError

AUTHOR = "Mayuresh Kulkarni"


def _ref(out):
    return messages.parse_share_link(out["link"])


def _recipient(skills_dir):
    installer.save_installed([])
    shutil.rmtree(skills_dir / "mine")


def _version_folder(provider, out, version):
    return provider.child_folder(out["folder"], f"v{version}", create=False)


def _publish_v2(provider, skill_id, skills_dir, text="Changed"):
    skill_md = skills_dir / "mine" / skill_id / "SKILL.md"
    skill_md.write_text(f"---\nname: Weekly Report\n---\n\n{text}\n", encoding="utf-8")
    return publisher.publish(provider, skill_id, author=AUTHOR)


def _installed_v1(provider, make_mine, skills_dir, **kwargs):
    """Author publishes v1; the same machine then becomes a recipient that installed it."""
    skill_id = make_mine(**kwargs)
    first = publisher.publish(provider, skill_id, author=AUTHOR)
    _recipient(skills_dir)
    receiver.install(provider, _ref(first), version=1, digest=first["digest"])
    return skill_id, first


# ── review: update vs collision ──────────────────────────────────────────


def test_review_of_the_same_source_is_an_update_not_a_collision(provider, make_mine, skills_dir):
    _skill_id, _first, second = _v2_for_a_recipient(provider, make_mine, skills_dir)

    card = receiver.review(provider, _ref(second))

    assert card["collision"] == ""
    assert card["installed_version"] == 1
    assert card["version"] == 2
    assert card["up_to_date"] is False


def test_review_says_up_to_date_when_the_installed_copy_matches(provider, make_mine, skills_dir):
    _skill_id, first = _installed_v1(provider, make_mine, skills_dir)
    card = receiver.review(provider, _ref(first))
    assert card["collision"] == ""
    assert card["installed_version"] == 1
    assert card["up_to_date"] is True


def test_a_first_review_has_no_installed_version(provider, make_mine, skills_dir):
    skill_id = make_mine()
    out = publisher.publish(provider, skill_id, author=AUTHOR)
    _recipient(skills_dir)
    card = receiver.review(provider, _ref(out))
    assert card["installed_version"] is None
    assert card["up_to_date"] is False


def test_a_same_named_skill_from_another_source_is_still_a_collision(provider, make_mine, skills_dir):
    skill_id, out = _installed_v1(provider, make_mine, skills_dir)
    skill_state.update_entry(skill_id, {"share_source": {"drive_id": "d1", "folder_id": "someone-elses"}})
    card = receiver.review(provider, _ref(out))
    assert card["collision"] == "installed"
    assert card["installed_version"] is None
    with pytest.raises(ShareError) as err:
        receiver.install(provider, _ref(out), version=1, digest=out["digest"])
    assert err.value.code == "collision"


def test_the_same_folder_id_on_another_drive_is_still_a_collision(provider, make_mine, skills_dir):
    skill_id, out = _installed_v1(provider, make_mine, skills_dir)
    source = skill_state.get_entry(skill_id)["share_source"]
    skill_state.update_entry(skill_id, {"share_source": {**source, "drive_id": "other-drive"}})
    assert receiver.review(provider, _ref(out))["collision"] == "installed"


def test_a_mine_skill_from_the_same_folder_is_still_a_collision(provider, make_mine):
    skill_id = make_mine()
    out = publisher.publish(provider, skill_id, author=AUTHOR)
    assert skill_state.get_entry(skill_id)["share_source"]["folder_id"] == out["folder"]["folder_id"]
    assert receiver.review(provider, _ref(out))["collision"] == "mine"


def test_a_built_in_name_is_still_a_collision(provider, make_mine, skills_dir):
    skill_id = make_mine(name="Email")
    out = publisher.publish(provider, skill_id, author=AUTHOR)
    _recipient(skills_dir)
    assert receiver.review(provider, _ref(out))["collision"] == "native"


# ── install: update in place ─────────────────────────────────────────────


def _v2_for_a_recipient(provider, make_mine, skills_dir):
    """Recipient holds v1; the author has published v2 to the same folder."""
    skill_id = make_mine()
    first = publisher.publish(provider, skill_id, author=AUTHOR)
    second = _publish_v2(provider, skill_id, skills_dir)
    _recipient(skills_dir)
    receiver.install(provider, _ref(first), version=1, digest=first["digest"])
    return skill_id, first, second


def test_update_changes_files_and_state(provider, make_mine, skills_dir):
    skill_id, _first, second = _v2_for_a_recipient(provider, make_mine, skills_dir)
    assert skill_state.get_entry(skill_id)["shared_version"] == 1

    result = receiver.install(provider, _ref(second), version=2, digest=second["digest"])

    assert result["ok"] is True
    assert "Changed" in (skills_dir / skill_id / "SKILL.md").read_text(encoding="utf-8")
    entry = skill_state.get_entry(skill_id)
    assert entry["tier"] == "Community"
    assert entry["version"] == "2"
    assert entry["shared_version"] == 2
    assert entry["files_digest"] == second["digest"]
    assert entry["shared_by"] == AUTHOR
    assert entry["share_source"] == {"drive_id": "d1", "folder_id": second["folder"]["folder_id"]}
    assert len([e for e in installer.load_installed() if e["id"] == skill_id]) == 1


def test_update_removes_files_the_new_version_no_longer_has(provider, make_mine, skills_dir):
    skill_id = make_mine(extra={"notes.md": b"old notes\n"})
    first = publisher.publish(provider, skill_id, author=AUTHOR)
    (skills_dir / "mine" / skill_id / "notes.md").unlink()
    second = _publish_v2(provider, skill_id, skills_dir)
    _recipient(skills_dir)
    receiver.install(provider, _ref(first), version=1, digest=first["digest"])
    assert (skills_dir / skill_id / "notes.md").exists()

    receiver.install(provider, _ref(second), version=2, digest=second["digest"])

    assert not (skills_dir / skill_id / "notes.md").exists()
    assert (skills_dir / skill_id / "SKILL.md").is_file()


def test_update_keeps_the_digest_recheck(provider, make_mine, skills_dir):
    skill_id, _first, second = _v2_for_a_recipient(provider, make_mine, skills_dir)
    before = (skills_dir / skill_id / "SKILL.md").read_bytes()
    with pytest.raises(ShareError) as err:
        receiver.install(provider, _ref(second), version=2, digest="0" * 64)
    assert err.value.code == "content_changed"
    assert (skills_dir / skill_id / "SKILL.md").read_bytes() == before
    assert skill_state.get_entry(skill_id)["shared_version"] == 1


def test_update_refuses_a_tampered_bundle_and_leaves_the_installed_copy(provider, make_mine, skills_dir):
    skill_id, _first, second = _v2_for_a_recipient(provider, make_mine, skills_dir)
    key = (_version_folder(provider, second, 2)["folder_id"], "bundle.zip")
    provider.files[key] = (provider.files[key][0] + b"x", '"edited"')
    before = (skills_dir / skill_id / "SKILL.md").read_bytes()
    with pytest.raises(ShareError) as err:
        receiver.install(provider, _ref(second), version=2, digest=second["digest"])
    assert err.value.code == "tampered"
    assert (skills_dir / skill_id / "SKILL.md").read_bytes() == before
    assert skill_state.get_entry(skill_id)["shared_version"] == 1


def test_a_plain_reinstall_keeps_files_it_did_not_write(skills_dir):
    installer.install_skill_md("keep-me", "# Keep me\n", "1", "Community")
    (skills_dir / "keep-me" / "extra.txt").write_text("x", encoding="utf-8")
    installer.install_skill_md("keep-me", "# Keep me\n", "2", "Community")
    assert (skills_dir / "keep-me" / "extra.txt").exists()


# ── update check ─────────────────────────────────────────────────────────


def test_check_update_reports_a_newer_version(provider, make_mine, skills_dir):
    skill_id, _first, second = _v2_for_a_recipient(provider, make_mine, skills_dir)
    found = receiver.check_update(provider, skill_id)
    assert found["status"] == "update"
    assert found["installed"] == 1
    assert found["latest"] == 2
    assert messages.parse_share_link(found["link"])["folder_id"] == second["folder"]["folder_id"]


def test_check_update_reports_current(provider, make_mine, skills_dir):
    skill_id, _first = _installed_v1(provider, make_mine, skills_dir)
    found = receiver.check_update(provider, skill_id)
    assert found["status"] == "current"
    assert found["latest"] == 1


def test_check_update_reports_a_removed_folder_and_keeps_the_copy(provider, make_mine, skills_dir):
    skill_id, first = _installed_v1(provider, make_mine, skills_dir)
    del provider.files[(first["folder"]["folder_id"], "skill.json")]
    assert receiver.check_update(provider, skill_id)["status"] == "removed"
    assert (skills_dir / skill_id / "SKILL.md").is_file()
    assert skill_state.get_entry(skill_id)["shared_version"] == 1


@pytest.mark.parametrize("code, status", [("forbidden", "no_access"), ("not_found", "removed")])
def test_check_update_maps_access_errors_to_a_status(provider, make_mine, skills_dir, code, status):
    skill_id, _first = _installed_v1(provider, make_mine, skills_dir)
    provider.fail_on["read_file"] = ShareError(code, "x")
    assert receiver.check_update(provider, skill_id)["status"] == status


def test_check_update_passes_other_errors_through(provider, make_mine, skills_dir):
    skill_id, _first = _installed_v1(provider, make_mine, skills_dir)
    provider.fail_on["read_file"] = ShareError("throttled", "slow")
    with pytest.raises(ShareError) as err:
        receiver.check_update(provider, skill_id)
    assert err.value.code == "throttled"


def test_check_update_only_applies_to_received_skills(provider, make_mine, skills_dir):
    mine = make_mine()
    installer.save_installed([*installer.load_installed(), {"id": "plain", "tier": "Community", "version": "1"}])
    for skill_id in (mine, "plain", "missing"):
        with pytest.raises(ShareError) as err:
            receiver.check_update(provider, skill_id)
        assert err.value.code == "invalid"


# ── routes ───────────────────────────────────────────────────────────────

UPDATE_CHECK = "/api/skills/share/update-check"


@pytest.fixture
def env(provider, skills_dir):
    app = FastAPI()
    app.include_router(router)
    with patch("routes.skill_sharing._provider", return_value=provider):
        yield SimpleNamespace(http=TestClient(app), provider=provider)


def test_update_check_route_reports_a_newer_version(env, make_mine, skills_dir):
    skill_id, _first, _second = _v2_for_a_recipient(env.provider, make_mine, skills_dir)
    res = env.http.get(UPDATE_CHECK, params={"skill_id": skill_id})
    assert res.status_code == 200
    assert res.json()["status"] == "update"
    assert res.json()["latest"] == 2


def test_update_check_route_reports_removed_and_no_access(env, make_mine, skills_dir):
    skill_id, first = _installed_v1(env.provider, make_mine, skills_dir)
    env.provider.fail_on["read_file"] = ShareError("forbidden", "no")
    assert env.http.get(UPDATE_CHECK, params={"skill_id": skill_id}).json()["status"] == "no_access"
    del env.provider.files[(first["folder"]["folder_id"], "skill.json")]
    assert env.http.get(UPDATE_CHECK, params={"skill_id": skill_id}).json()["status"] == "removed"


def test_update_check_route_refuses_a_skill_that_was_not_shared_with_you(env):
    installer.save_installed([{"id": "plain", "tier": "Community", "version": "1"}])
    res = env.http.get(UPDATE_CHECK, params={"skill_id": "plain"})
    assert res.status_code == 400
    assert res.json()["detail"]["error"] == "invalid"


def test_update_check_route_needs_a_skill_id(env):
    assert env.http.get(UPDATE_CHECK).status_code == 422


# ── author side: edits since the last share ──────────────────────────────


def test_unshared_edits_is_false_right_after_publishing(provider, make_mine):
    skill_id = make_mine()
    publisher.publish(provider, skill_id, author=AUTHOR)
    assert publisher.has_unshared_edits(skill_state.get_entry(skill_id)) is False


def test_unshared_edits_is_true_after_a_change(provider, make_mine, skills_dir):
    skill_id = make_mine()
    publisher.publish(provider, skill_id, author=AUTHOR)
    (skills_dir / "mine" / skill_id / "SKILL.md").write_text("---\nname: Weekly Report\n---\n\nEdited\n", encoding="utf-8")
    assert publisher.has_unshared_edits(skill_state.get_entry(skill_id)) is True


def test_unshared_edits_is_false_again_after_republishing(provider, make_mine, skills_dir):
    skill_id = make_mine()
    publisher.publish(provider, skill_id, author=AUTHOR)
    _publish_v2(provider, skill_id, skills_dir)
    assert publisher.has_unshared_edits(skill_state.get_entry(skill_id)) is False


def test_unshared_edits_needs_a_mine_skill_that_was_published(make_mine, skills_dir):
    skill_id = make_mine()
    assert publisher.has_unshared_edits(skill_state.get_entry(skill_id)) is False
    assert publisher.has_unshared_edits({"id": "x", "tier": "Community", "published_digest": "abc"}) is False


def test_unshared_edits_is_false_when_the_files_are_gone(provider, make_mine, skills_dir):
    skill_id = make_mine()
    publisher.publish(provider, skill_id, author=AUTHOR)
    shutil.rmtree(skills_dir / "mine" / skill_id)
    assert publisher.has_unshared_edits(skill_state.get_entry(skill_id)) is False


def test_the_installed_list_carries_unshared_edits_for_published_mine_skills(provider, make_mine, skills_dir):
    from routes import marketplace as marketplace_routes

    skill_id = make_mine()
    other = make_mine(name="Never Shared")
    publisher.publish(provider, skill_id, author=AUTHOR)
    app = FastAPI()
    app.include_router(marketplace_routes.router)
    http = TestClient(app)

    def listed():
        return {s["id"]: s for s in http.get("/api/marketplace/installed").json()["skills"]}

    first = listed()
    assert first[skill_id]["unshared_edits"] is False
    assert "unshared_edits" not in first[other]

    (skills_dir / "mine" / skill_id / "SKILL.md").write_text("---\nname: Weekly Report\n---\n\nEdited\n", encoding="utf-8")
    assert listed()[skill_id]["unshared_edits"] is True
