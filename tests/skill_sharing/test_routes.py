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
from sandbox import policy as _policy
from security import get_csrf_token
from skills._sharing import messages
from skills._sharing.errors import ShareError

PUBLISH = "/api/skills/share/publish"
PREVIEW = "/api/skills/share/preview"
REVIEW = "/api/skills/share/review"
INSTALL = "/api/skills/share/install"
DRAFT = "/api/skills/share/draft"
LOCATIONS = "/api/skills/share/locations"
CHECK = "/api/skills/share/check"


@pytest.fixture
def env(provider, skills_dir):
    app = FastAPI()
    app.include_router(router)
    with (
        patch("routes.skill_sharing._provider", return_value=provider),
        patch("routes.skill_sharing._author_name", return_value="Mayuresh Kulkarni"),
        patch("routes.skill_sharing.load_installed_skill_prompts") as prompts,
        patch("routes.skill_sharing.load_skill_tools", return_value={"ok": True}) as tools,
        patch("routes.skill_sharing.skill_audit.log_install") as audit,
    ):
        yield SimpleNamespace(
            http=TestClient(app), provider=provider, skills_dir=skills_dir, prompts=prompts, tools=tools, audit=audit
        )


def _post(env, path, body, headers=True):
    return env.http.post(path, json=body, headers={"X-CSRF-Token": get_csrf_token("testserver")} if headers else {})


def _published_for_a_recipient(env, make_mine):
    skill_id = make_mine()
    body = _post(env, PUBLISH, {"skill_id": skill_id}).json()
    installer.save_installed([])
    shutil.rmtree(env.skills_dir / "mine")
    return skill_id, body


@pytest.mark.parametrize("path", [PUBLISH, REVIEW, INSTALL, DRAFT])
def test_every_route_rejects_a_missing_csrf_token(env, path):
    assert _post(env, path, {}, headers=False).status_code == 403


def test_publish_returns_the_link_and_records_the_share(env, make_mine):
    skill_id = make_mine()
    res = _post(env, PUBLISH, {"skill_id": skill_id, "people": ["a@contoso.com"]})

    assert res.status_code == 200
    body = res.json()
    assert body["version"] == 1
    assert body["reused"] is False
    assert messages.parse_share_link(body["link"])["folder_id"] == body["folder"]["folder_id"]
    assert body["message"]
    assert body["link"] in body["message"]
    assert env.provider.grants == [(body["folder"]["folder_id"], ["a@contoso.com"])]
    assert skill_state.get_entry(skill_id)["published_version"] == 1


def test_publish_reports_addresses_that_could_not_be_granted(env, make_mine):
    env.provider.ungrantable.add("outside@gmail.com")
    res = _post(env, PUBLISH, {"skill_id": make_mine(), "people": ["a@contoso.com", "outside@gmail.com"]})

    assert res.status_code == 200
    assert res.json()["ungranted"] == ["outside@gmail.com"]
    assert res.json()["link"]


def _draft_body(**over):
    return {"skill_id": "s", "channel": "email", "people": [{"name": "Ann", "email": "A@Contoso.com"}], "message": "Hello", **over}


def test_draft_route_hands_the_people_and_message_to_the_drafter(env):
    with patch("routes.skill_sharing.drafts.build", return_value={"drafts": [], "unmatched": []}) as build:
        res = _post(env, DRAFT, _draft_body())
    assert res.status_code == 200
    build.assert_called_once_with(
        skill_id="s", people=[{"name": "Ann", "email": "A@Contoso.com"}], message="Hello", message_html="", note=""
    )


def test_draft_route_passes_the_html_message_through(env):
    with patch("routes.skill_sharing.drafts.build", return_value={"drafts": [], "unmatched": []}) as build:
        res = _post(env, DRAFT, _draft_body(message_html="<p>Hi</p>"))
    assert res.status_code == 200
    assert build.call_args.kwargs["message_html"] == "<p>Hi</p>"


def test_draft_route_passes_the_note_through(env):
    with patch("routes.skill_sharing.drafts.build", return_value={"drafts": [], "unmatched": []}) as build:
        res = _post(env, DRAFT, _draft_body(note="Hi Ann"))
    assert res.status_code == 200
    assert build.call_args.kwargs["note"] == "Hi Ann"


def test_the_note_is_in_the_drafted_email_and_nothing_is_sent(env):
    with patch("routes.drafts.approve_draft") as approve:
        res = _post(env, DRAFT, _draft_body(note="Hi Ann"))
    assert res.status_code == 200
    approve.assert_not_called()
    data = res.json()["drafts"][0]["data"]
    assert data["body"] == "Hi Ann\n\nHello"


def test_draft_route_names_are_optional(env):
    with patch("routes.skill_sharing.drafts.build", return_value={"drafts": [], "unmatched": []}) as build:
        res = _post(env, DRAFT, _draft_body(people=[{"email": "a@contoso.com"}]))
    assert res.status_code == 200
    assert build.call_args.kwargs["people"] == [{"name": "", "email": "a@contoso.com"}]


@pytest.mark.parametrize(
    "over",
    [
        {"channel": "teams"},
        {"channel": "slack"},
        {"people": []},
        {"people": ["a@contoso.com"]},
        {"people": [{"email": "not-an-email"}]},
        {"message": ""},
        {"message": "x" * 4001},
    ],
)
def test_draft_route_rejects_bad_input(env, over):
    assert _post(env, DRAFT, _draft_body(**over)).status_code == 422


def test_publish_refuses_a_skill_that_is_not_mine(env):
    installer.save_installed([{"id": "someone-elses", "tier": "Community", "version": "1"}])
    res = _post(env, PUBLISH, {"skill_id": "someone-elses"})
    assert res.status_code == 400
    assert res.json()["detail"]["error"] == "not_mine"


@pytest.mark.parametrize("people", [["not-an-email"], ["a@b"], ["a@contoso.com, b@contoso.com"], ["a@c.com"] * 51])
def test_publish_rejects_bad_people(env, make_mine, people):
    res = _post(env, PUBLISH, {"skill_id": make_mine(), "people": people})
    assert res.status_code == 422
    assert env.provider.writes == []


def test_review_returns_the_card_and_installs_nothing(env, make_mine):
    skill_id, shared = _published_for_a_recipient(env, make_mine)
    res = _post(env, REVIEW, {"link": shared["link"]})

    assert res.status_code == 200
    card = res.json()
    assert card["skill_id"] == skill_id
    assert card["digest"] == shared["digest"]
    assert card["collision"] == ""
    assert installer.load_installed() == []


def test_review_rejects_a_bad_link(env):
    res = _post(env, REVIEW, {"link": "https://example.com/not-ours"})
    assert res.status_code == 400
    assert res.json()["detail"]["error"] == "invalid_link"


def test_review_of_a_removed_skill_is_a_404(env):
    link = messages.make_share_link({"drive_id": "d1", "folder_id": "gone"})
    res = _post(env, REVIEW, {"link": link})
    assert res.status_code == 404
    assert res.json()["detail"]["error"] == "not_found"


@pytest.mark.parametrize(
    "failure, status",
    [
        (ShareError("forbidden", "no access"), 422),
        (ShareError("throttled", "slow down"), 429),
        (ShareError("locked", "locked"), 423),
        (ShareError("conflict", "changed"), 409),
        (RuntimeError("boom"), 502),
    ],
)
def test_provider_failures_never_surface_as_403(env, make_mine, failure, status):
    _skill_id, shared = _published_for_a_recipient(env, make_mine)
    env.provider.fail_on["read_file"] = failure
    res = _post(env, REVIEW, {"link": shared["link"]})
    assert res.status_code == status
    assert "message" in res.json()["detail"]


def test_install_pins_the_reviewed_digest_and_keeps_the_share_state(env, make_mine):
    skill_id, shared = _published_for_a_recipient(env, make_mine)
    res = _post(env, INSTALL, {"link": shared["link"], "version": 1, "digest": shared["digest"]})

    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert (env.skills_dir / skill_id / "SKILL.md").is_file()
    entry = skill_state.get_entry(skill_id)
    assert entry["shared_version"] == 1
    assert entry["share_source"]["folder_id"] == shared["folder"]["folder_id"]
    assert entry["tier"] == "Community"
    env.prompts.assert_called_once()
    env.tools.assert_called_once()
    env.audit.assert_called_once_with(skill_id, "Community", "share", shared["digest"])


def test_install_requires_a_digest(env, make_mine):
    _skill_id, shared = _published_for_a_recipient(env, make_mine)
    res = _post(env, INSTALL, {"link": shared["link"], "version": 1, "digest": ""})
    assert res.status_code == 400
    assert installer.load_installed() == []


def test_install_of_changed_content_is_a_409(env, make_mine):
    _skill_id, shared = _published_for_a_recipient(env, make_mine)
    res = _post(env, INSTALL, {"link": shared["link"], "version": 1, "digest": "0" * 64})
    assert res.status_code == 409
    assert res.json()["detail"]["error"] == "content_changed"
    assert installer.load_installed() == []


def test_install_refuses_a_name_collision(env, make_mine):
    skill_id = make_mine()
    shared = _post(env, PUBLISH, {"skill_id": skill_id}).json()
    res = _post(env, INSTALL, {"link": shared["link"], "version": 1, "digest": shared["digest"]})
    assert res.status_code == 409
    assert res.json()["detail"]["error"] == "collision"
    assert skill_state.get_entry(skill_id)["tier"] == "Mine"


def test_install_keeps_the_admin_allow_list(env, make_mine, tmp_path):
    _skill_id, shared = _published_for_a_recipient(env, make_mine)
    (tmp_path / "sandbox-policy.json").write_text(json.dumps({"approved_digests": []}), encoding="utf-8")
    _policy._reset_cache()
    res = _post(env, INSTALL, {"link": shared["link"], "version": 1, "digest": shared["digest"]})
    assert res.status_code == 403
    assert res.json()["detail"]["error"] == "digest_not_approved"
    assert installer.load_installed() == []


def test_install_keeps_the_tier_policy(env, make_mine, tmp_path):
    _skill_id, shared = _published_for_a_recipient(env, make_mine)
    (tmp_path / "sandbox-policy.json").write_text(
        json.dumps({"marketplace_allowed_tiers": ["Native", "Verified"]}), encoding="utf-8"
    )
    _policy._reset_cache()
    res = _post(env, INSTALL, {"link": shared["link"], "version": 1, "digest": shared["digest"]})
    assert res.status_code == 403
    assert installer.load_installed() == []


def _ref(folder):
    return {k: folder[k] for k in ("drive_id", "folder_id", "web_url", "name")}


def test_locations_returns_default_recent_and_current(env, make_mine):
    skill_id = make_mine()
    res = env.http.get(LOCATIONS, params={"skill_id": skill_id})
    assert res.status_code == 200
    body = res.json()
    assert body["default"]["path"] == ["OneDrive", "AI Gator Skills"]
    assert body["recent"] == []
    assert body["current"] is None


def test_locations_needs_a_skill_id(env):
    assert env.http.get(LOCATIONS).status_code == 422


def test_check_with_no_folder_checks_the_default(env, make_mine):
    res = env.http.get(CHECK, params={"skill_id": make_mine()})
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert res.json()["audience"]["kind"] == "private"


@pytest.mark.parametrize("params", [{"drive_id": "d1"}, {"folder_id": "f1"}])
def test_check_with_half_a_folder_is_a_400(env, make_mine, params):
    res = env.http.get(CHECK, params={"skill_id": make_mine(), **params})
    assert res.status_code == 400
    assert res.json()["detail"]["error"] == "invalid"


def test_check_of_a_missing_folder_is_ok_false_not_an_error(env, make_mine):
    res = env.http.get(CHECK, params={"skill_id": make_mine(), "drive_id": "d1", "folder_id": "nope"})
    assert res.status_code == 200
    assert res.json()["ok"] is False
    assert res.json()["reason"] == "not_found"


def test_check_reports_the_audience_and_an_existing_skill(env, make_mine):
    chosen = env.provider.child_folder(env.provider.default_root(), "Team")
    env.provider.audiences[chosen["folder_id"]] = {"kind": "org", "name": "Your organization", "approx_count": None}
    skill_id = make_mine()
    _post(env, PUBLISH, {"skill_id": skill_id, "root": _ref(chosen), "audience_ack": True})
    body = env.http.get(CHECK, params={"skill_id": skill_id, "drive_id": "d1", "folder_id": chosen["folder_id"]}).json()
    assert body["audience"]["kind"] == "org"
    assert body["existing"]["yours"] is True


def test_publish_to_a_chosen_folder_returns_where_it_went(env, make_mine):
    chosen = env.provider.child_folder(env.provider.default_root(), "Team")
    skill_id = make_mine()
    res = _post(env, PUBLISH, {"skill_id": skill_id, "root": _ref(chosen)})
    assert res.status_code == 200
    assert res.json()["saved_path"] == ["OneDrive", "AI Gator Skills", "Team", skill_id]
    assert env.http.get(LOCATIONS, params={"skill_id": skill_id}).json()["recent"][0]["folder_id"] == chosen["folder_id"]


def test_publish_to_a_shared_folder_needs_acknowledgement(env, make_mine):
    chosen = env.provider.child_folder(env.provider.default_root(), "Team")
    env.provider.audiences[chosen["folder_id"]] = {"kind": "folder", "name": "Team", "approx_count": 3}
    skill_id = make_mine()
    res = _post(env, PUBLISH, {"skill_id": skill_id, "root": _ref(chosen)})
    assert res.status_code == 422
    assert res.json()["detail"]["error"] == "audience_unacknowledged"
    assert env.provider.writes == []
    assert _post(env, PUBLISH, {"skill_id": skill_id, "root": _ref(chosen), "audience_ack": True}).status_code == 200


def test_publish_into_someone_elses_skill_is_a_409(env, make_mine):
    chosen = env.provider.child_folder(env.provider.default_root(), "Team")
    skill_id = make_mine()
    theirs = env.provider.child_folder(chosen, skill_id)
    env.provider.files[(theirs["folder_id"], "skill.json")] = (
        json.dumps({"latest": 1, "versions": [], "author": "Bob"}).encode(),
        '"e1"',
    )
    res = _post(env, PUBLISH, {"skill_id": skill_id, "root": _ref(chosen)})
    assert res.status_code == 409
    assert res.json()["detail"]["error"] == "not_yours"


def test_a_policy_refusal_is_a_422_with_its_own_code(env, make_mine):
    env.provider.fail_on["write_file"] = ShareError("forbidden", "label")
    res = _post(env, PUBLISH, {"skill_id": make_mine()})
    assert res.status_code == 422
    assert res.json()["detail"]["error"] == "policy_blocked"


def test_publish_to_a_folder_that_is_gone_is_a_404(env, make_mine):
    root = {"drive_id": "d1", "folder_id": "nope"}
    res = _post(env, PUBLISH, {"skill_id": make_mine(), "root": root})
    assert res.status_code == 404
    assert res.json()["detail"]["error"] == "not_found"


def test_the_new_read_routes_need_no_csrf_token(env, make_mine):
    assert env.http.get(LOCATIONS, params={"skill_id": make_mine()}).status_code == 200


def test_preview_shows_the_real_message_with_the_link_left_out_and_writes_nothing(env, make_mine):
    skill_id = make_mine()
    res = env.http.get(PREVIEW, params={"skill_id": skill_id})

    assert res.status_code == 200
    assert res.json()["title"] == "Weekly Report"
    message = res.json()["message"]
    assert "Mayuresh Kulkarni" in message
    assert "Weekly Report" in message
    assert messages.LINK_PLACEHOLDER in message
    assert "aigator://share?d=" not in message
    assert env.provider.folders == {} and env.provider.writes == [] and env.provider.grants == []
    assert skill_state.get_entry(skill_id).get("share_source") is None


def test_preview_is_the_published_message_with_only_the_link_and_address_swapped(env, make_mine):
    skill_id = make_mine()
    preview = env.http.get(PREVIEW, params={"skill_id": skill_id}).json()["message"]
    published = _post(env, PUBLISH, {"skill_id": skill_id}).json()
    expected = published["message"].replace(published["link"], messages.LINK_PLACEHOLDER).replace(
        published["web_url"], messages.LINK_PLACEHOLDER
    )
    assert preview == expected


def test_preview_refuses_a_skill_that_is_not_yours(env):
    res = env.http.get(PREVIEW, params={"skill_id": "nothing-here"})
    assert res.status_code == 400
    assert res.json()["detail"]["error"] == "not_mine"
