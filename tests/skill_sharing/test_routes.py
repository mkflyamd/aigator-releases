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
REVIEW = "/api/skills/share/review"
INSTALL = "/api/skills/share/install"


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


@pytest.mark.parametrize("path", [PUBLISH, REVIEW, INSTALL])
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
