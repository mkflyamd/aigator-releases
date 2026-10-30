"""A GitHub org that has not authorized the user's gh login produces a chat card, not a wall of error text."""

import asyncio
import io
import json
import pathlib
import subprocess
import sys
import urllib.error
from types import SimpleNamespace

import pytest

import config
from sandbox import approvals, task_grants
from skills.github import api, credentials, gh_cli, sso
from skills.github import tools as gh_tools
from skills.shell_runner import tools as _shell_runner  # noqa: F401  (loaded before subprocess.run is patched)

ROOT = pathlib.Path(__file__).parent.parent
FAKE = "aigator-fake-api-key"
GH_SAML = (
    "gh: Resource protected by organization SAML enforcement. You must grant your OAuth token access to this "
    "organization. The 'ROCm' organization has enabled or enforced SAML SSO. To access this repository, visit "
    "https://github.com/orgs/ROCm/sso?authorization_request=CBLRZTAGUPDPWOHXOYMLJXLK4POBRA and try your request "
    "again. (HTTP 403)"
)
ONE_TIME = "https://github.com/orgs/ROCm/sso?authorization_request=CBLRZTAGUPDPWOHXOYMLJXLK4POBRA"
PAT_BLOCKED = '{"message":"`ROCm` forbids access via a personal access token (classic)."}'


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setattr(credentials, "_saved", lambda: {"github_token": FAKE})
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(config, "WORK_DIR", work)
    approvals._reset()
    task_grants._reset()
    yield
    approvals._reset()
    task_grants._reset()


def _refused_rest(monkeypatch):
    def urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 403, "x", {}, io.BytesIO(PAT_BLOCKED.encode()))

    monkeypatch.setattr(api.urllib.request, "urlopen", urlopen)


def _gh(monkeypatch, stderr, exit_code=1, stdout=""):
    def run(cmd, **kw):
        if cmd[1:3] == ["auth", "status"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, exit_code, stdout, stderr)

    monkeypatch.setattr(gh_cli.subprocess, "run", run)
    monkeypatch.setattr(gh_cli.shutil, "which", lambda name: "/usr/bin/gh")


def test_card_names_the_org_and_links_its_sso_page():
    assert sso.card_for(GH_SAML) == {"org": "ROCm", "url": ONE_TIME}


def test_card_uses_the_one_time_link_that_authorizes_the_token():
    card = sso.card_for(GH_SAML)
    assert card["url"] == ONE_TIME


def test_card_ignores_a_one_time_link_for_another_host_or_org():
    text = "SAML SSO. The 'ROCm' organization. visit https://evil.example/orgs/ROCm/sso?authorization_request=AB"
    assert sso.card_for(text)["url"] == "https://github.com/orgs/ROCm/sso"
    text = "SAML SSO. visit https://github.com/orgs/other/sso?authorization_request=AB"
    assert sso.card_for(text) == {"org": "other", "url": "https://github.com/orgs/other/sso?authorization_request=AB"}


def test_card_org_falls_back_to_the_repo_owner():
    text = "Resource protected by organization SAML enforcement."
    assert sso.card_for(text, owner="amd")["url"] == "https://github.com/orgs/amd/sso"
    assert sso.card_for(text) is None


@pytest.mark.parametrize("text", ["HTTP 404: Not Found", "gh: not signed in", ""])
def test_no_card_without_a_saml_refusal(text):
    assert sso.card_for(text, owner="amd") is None


def test_card_never_builds_a_link_from_an_unsafe_org_name():
    assert sso.card_for("SAML enforcement. The 'a/../evil' organization", owner="") is None
    assert sso.card_for("SAML enforcement.", owner="a b") is None


def test_enterprise_card_links_the_enterprise_host(monkeypatch):
    monkeypatch.setattr(credentials, "_saved", lambda: {"github_base_url": "https://ghe.example.com"})
    assert sso.card_for(GH_SAML)["url"] == "https://ghe.example.com/orgs/ROCm/sso"  # one-time link is for another host


def test_refused_read_with_saml_returns_a_card_and_a_short_error(monkeypatch):
    _refused_rest(monkeypatch)
    _gh(monkeypatch, GH_SAML)

    result = api._rest("/repos/ROCm/rocm-systems/pulls/482")

    assert result["_github_sso"] == {"org": "ROCm", "url": ONE_TIME}
    assert "ROCm" in result["error"] and "http" not in result["error"]
    assert "authorization_request" not in result["error"] + result["assistant_guidance"]
    assert "do not open the public page" in result["assistant_guidance"]
    assert "card" in result["assistant_guidance"] and "retry" in result["assistant_guidance"].lower()


def _gh_as(monkeypatch, login):
    def run(cmd, **kw):
        if cmd[1:3] == ["auth", "status"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[1:3] == ["api", "user"]:
            return subprocess.CompletedProcess(cmd, 0, login + "\n", "")
        return subprocess.CompletedProcess(cmd, 1, "", GH_SAML)

    monkeypatch.setattr(gh_cli.subprocess, "run", run)
    monkeypatch.setattr(gh_cli.shutil, "which", lambda name: "/usr/bin/gh")


def test_card_names_the_account_gh_runs_as(monkeypatch):
    _refused_rest(monkeypatch)
    _gh_as(monkeypatch, "maykulka_amdeng")

    result = api._rest("/repos/ROCm/rocm-systems/pulls/482")

    assert result["_github_sso"] == {"org": "ROCm", "url": ONE_TIME, "account": "maykulka_amdeng"}


def test_card_leaves_out_an_account_name_that_is_not_a_login(monkeypatch):
    _gh_as(monkeypatch, "<b>evil</b>")
    assert "account" not in gh_tools._github_gh(["pr", "view", "1", "-R", "ROCm/aiter"])["_github_sso"]


def test_other_gh_failures_keep_the_full_error_and_show_no_card(monkeypatch):
    _refused_rest(monkeypatch)
    _gh(monkeypatch, "HTTP 403: Forbidden")

    result = api._rest("/repos/ROCm/rocm-systems/pulls/482")

    assert "_github_sso" not in result
    assert "forbids access via a personal access token" in result["error"]
    assert "HTTP 403: Forbidden" in result["error"]


def test_get_pr_passes_the_card_through(monkeypatch):
    _refused_rest(monkeypatch)
    _gh(monkeypatch, GH_SAML)
    assert gh_tools._github_get_pr("ROCm", "rocm-systems", 482)["_github_sso"]["org"] == "ROCm"


def test_get_issue_passes_the_card_through(monkeypatch):
    _refused_rest(monkeypatch)
    _gh(monkeypatch, GH_SAML)
    assert gh_tools._github_get_issue("ROCm", "aiter", 1)["_github_sso"]["org"] == "ROCm"


def test_github_gh_tool_adds_the_card_when_gh_is_refused_by_saml(monkeypatch):
    _gh(monkeypatch, GH_SAML)

    result = gh_tools._github_gh(["pr", "view", "6335", "-R", "ROCm/aiter"])

    assert result["_github_sso"] == {"org": "ROCm", "url": ONE_TIME}
    assert "assistant_guidance" in result


def test_github_gh_tool_unchanged_for_other_failures(monkeypatch):
    _gh(monkeypatch, "HTTP 404: Not Found")
    result = gh_tools._github_gh(["pr", "view", "1", "-R", "o/r"])
    assert "_github_sso" not in result and "HTTP 404" in result["error"]


def test_runner_emits_a_github_sso_event():
    from agent_loop import _make_tool_runner

    card = {"org": "ROCm", "url": ONE_TIME}

    async def fake_execute(name, inputs, **kw):
        return {"error": "needs sso", "_github_sso": card}

    run_tool_block, _, _ = _make_tool_runner(fake_execute, set(), {}, lambda n, r: None, "__slack_safe__")

    async def go():
        q = asyncio.Queue()
        await run_tool_block(SimpleNamespace(name="github_get_pr", inputs={}, id="c1"), q)
        return [q.get_nowait() for _ in range(q.qsize())]

    loop = asyncio.new_event_loop()
    try:
        events = loop.run_until_complete(go())
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())
    assert {"kind": "github_sso", "data": card} in events


def test_both_stream_loops_forward_github_sso():
    src = (ROOT / "web" / "agent_loop.py").read_text(encoding="utf-8")
    assert src.count("yield f\"data: {json.dumps({'github_sso': evt.get('data', {})})}\\n\\n\"") == 2


def test_the_retry_message_the_card_sends_continues_the_previous_turn():
    sys.path.insert(0, str(ROOT / "web"))
    from routes.chat import _continues_the_previous_turn as cont

    retry = "✅ Authorized · I authorized GitHub SSO for ROCm. Retry the GitHub request that just failed."
    assert cont(retry, set())
    assert not cont("Authorized · the budget for next year", set())


def test_open_is_the_highlighted_step_until_it_is_clicked():
    app_js = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "_setSsoStep" in app_js


def test_the_chat_ui_draws_the_card_and_opens_the_sso_page():
    app_js = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "msg.github_sso" in app_js
    assert "function _showGithubSsoCard" in app_js
    assert "openExternal(data.url)" in app_js
    assert "I authorized GitHub SSO for" in app_js
    assert "data.account" in app_js


def test_skill_tells_the_model_how_to_handle_the_card():
    text = (ROOT / "web" / "skills" / "github" / "SKILL.md").read_text(encoding="utf-8")
    assert "SSO" in text and "assistant_guidance" in text


STATUS = json.dumps({"hosts": {"github.com": [
    {"login": "mkflyamd", "active": True, "state": "success", "host": "github.com"},
    {"login": "maykulka_amdeng", "active": False, "state": "success", "host": "github.com"},
]}})
OTHER_TOKEN = "aigator-fake-api-key"


def _two_accounts(monkeypatch, works_for=()):
    """gh with two logins; commands run with GH_TOKEN=OTHER_TOKEN succeed only if the account is in works_for."""
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw.get("env", {})))
        if cmd[1:3] == ["auth", "status"] and "--json" in cmd:
            return subprocess.CompletedProcess(cmd, 0, STATUS, "")
        if cmd[1:3] == ["auth", "status"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[1:3] == ["auth", "token"]:
            return subprocess.CompletedProcess(cmd, 0, OTHER_TOKEN + "::" + cmd[-1] + "\n", "")
        if cmd[1:3] == ["auth", "switch"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[1:3] == ["api", "user"]:
            return subprocess.CompletedProcess(cmd, 0, "mkflyamd\n", "")
        token = kw.get("env", {}).get("GH_TOKEN", "")
        if token and token.split("::", 1)[1] in works_for:
            return subprocess.CompletedProcess(cmd, 0, '{"number": 6335, "token": "' + token + '"}', "")
        return subprocess.CompletedProcess(cmd, 1, "", GH_SAML)

    monkeypatch.setattr(gh_cli.subprocess, "run", run)
    monkeypatch.setattr(gh_cli.shutil, "which", lambda name: "/usr/bin/gh")
    return calls


def test_accounts_lists_logins_without_tokens(monkeypatch):
    _two_accounts(monkeypatch)
    assert gh_cli.accounts() == [{"login": "mkflyamd", "active": True},
                                 {"login": "maykulka_amdeng", "active": False}]
    assert gh_cli.other_accounts() == ["maykulka_amdeng"]


def test_refused_read_succeeds_as_the_other_account_with_no_card(monkeypatch):
    _refused_rest(monkeypatch)
    calls = _two_accounts(monkeypatch, works_for=("maykulka_amdeng",))

    result = api._rest("/repos/ROCm/aiter/pulls/6335")

    assert result["number"] == 6335
    assert "_github_sso" not in result
    assert not any(c[0][1:3] == ["auth", "switch"] for c in calls)


def test_other_account_token_never_leaks_into_the_result(monkeypatch):
    _two_accounts(monkeypatch, works_for=("maykulka_amdeng",))
    result = gh_tools._github_gh(["pr", "view", "6335", "-R", "ROCm/aiter", "--json", "number"])
    assert result["auth"] == "gh login (maykulka_amdeng)"
    assert OTHER_TOKEN not in json.dumps(result)


def test_card_lists_the_other_accounts_when_none_can_read(monkeypatch):
    _refused_rest(monkeypatch)
    _two_accounts(monkeypatch)

    card = api._rest("/repos/ROCm/aiter/pulls/6335")["_github_sso"]

    assert card["account"] == "mkflyamd" and card["others"] == ["maykulka_amdeng"]


@pytest.mark.parametrize("args", [["pr", "comment", "1", "-b", "x"], ["pr", "create"], ["issue", "close", "1"],
                                  ["api", "-X", "POST", "repos/o/r/issues"]])
def test_writes_are_never_retried_as_another_account(monkeypatch, args):
    calls = _two_accounts(monkeypatch, works_for=("maykulka_amdeng",))
    result = gh_tools._github_gh(args)
    assert "_github_sso" in result or "error" in result
    assert not any(c[0][1:3] == ["auth", "token"] for c in calls)


def test_read_only_check():
    assert gh_cli.is_read_only(["pr", "view", "1", "-R", "o/r"])
    assert gh_cli.is_read_only(["api", "repos/o/r"])
    assert not gh_cli.is_read_only(["pr", "merge", "1"])
    assert not gh_cli.is_read_only(["api", "repos/o/r", "-X", "DELETE"])
    assert not gh_cli.is_read_only(["auth", "token"])


def test_switch_account_runs_gh_auth_switch_for_a_known_login(monkeypatch):
    calls = _two_accounts(monkeypatch)
    assert gh_cli.switch_account("maykulka_amdeng") == {"ok": True, "account": "maykulka_amdeng"}
    assert any(c[0][1:] == ["auth", "switch", "--hostname", "github.com", "--user", "maykulka_amdeng"] for c in calls)


@pytest.mark.parametrize("login", ["stranger", "", "a b", "x; rm -rf /", "-u"])
def test_switch_account_refuses_a_login_gh_does_not_hold(monkeypatch, login):
    calls = _two_accounts(monkeypatch)
    assert gh_cli.switch_account(login)["ok"] is False
    assert not any(c[0][1:3] == ["auth", "switch"] for c in calls)


def test_switch_route_is_csrf_protected_and_switches(monkeypatch):
    sys.path.insert(0, str(ROOT / "web"))
    from fastapi.testclient import TestClient
    from app import app

    seen = []
    monkeypatch.setattr(gh_cli, "switch_account", lambda login: seen.append(login) or {"ok": True, "account": login})
    client = TestClient(app)
    assert client.post("/api/github/switch-account", json={"account": "maykulka_amdeng"}).status_code in (401, 403)
    assert seen == []
    token = client.get("/api/csrf").json()["csrf_token"]
    res = client.post("/api/github/switch-account", json={"account": "maykulka_amdeng"},
                      headers={"X-CSRF-Token": token})
    assert res.status_code == 200 and seen == ["maykulka_amdeng"]


def test_card_offers_use_account_buttons_that_retry():
    app_js = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "/api/github/switch-account" in app_js and "data.others" in app_js
    assert "by switching GitHub to" in app_js


def test_the_switch_retry_message_continues_the_previous_turn():
    sys.path.insert(0, str(ROOT / "web"))
    from routes.chat import _continues_the_previous_turn as cont

    assert cont("✅ Authorized · I authorized GitHub SSO for ROCm by switching GitHub to maykulka_amdeng. Retry.", set())


def _public_after_refusal(monkeypatch, public_ok=True):
    seen = []

    def urlopen(req, timeout=None):
        seen.append(req.get_header("Authorization"))
        if req.get_header("Authorization"):
            raise urllib.error.HTTPError(req.full_url, 403, "x", {}, io.BytesIO(PAT_BLOCKED.encode()))
        if not public_ok:
            raise urllib.error.HTTPError(req.full_url, 404, "x", {}, io.BytesIO(b"Not Found"))
        return io.BytesIO(b'{"number": 6335, "title": "public"}')

    class _Ctx(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(api.urllib.request, "urlopen", lambda req, timeout=None: _Ctx(urlopen(req, timeout).getvalue()))
    return seen


def test_public_repo_is_read_without_a_token_and_shows_no_card(monkeypatch):
    seen = _public_after_refusal(monkeypatch)
    _two_accounts(monkeypatch)

    result = api._rest("/repos/ROCm/aiter/pulls/6335")

    assert result == {"number": 6335, "title": "public"}
    assert seen[-1] is None


def test_public_read_works_when_gh_is_not_signed_in(monkeypatch):
    _public_after_refusal(monkeypatch)
    _gh_returns = lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "")  # noqa: E731
    monkeypatch.setattr(gh_cli.subprocess, "run", _gh_returns)
    monkeypatch.setattr(gh_cli.shutil, "which", lambda name: "/usr/bin/gh")

    assert api._rest("/repos/amd/skills/issues/283")["number"] == 6335


def test_private_repo_still_gets_the_card(monkeypatch):
    _public_after_refusal(monkeypatch, public_ok=False)
    _two_accounts(monkeypatch)

    assert api._rest("/repos/ROCm/private/pulls/1")["_github_sso"]["org"] == "ROCm"


def test_pr_result_has_no_files_key_that_the_chat_would_draw_as_download_cards():
    out = gh_tools._slim_pr({"number": 1}, [], [], [], [], [{"filename": "a.py", "additions": 1, "deletions": 0}])
    assert "files" not in out
    assert out["files_changed"][0]["filename"] == "a.py"
