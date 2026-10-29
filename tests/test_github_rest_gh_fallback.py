"""A saved token the org rejects (classic PAT ban, SAML SSO) falls back to the user's own gh login."""

import io
import json
import subprocess
import urllib.error

import pytest

import config
from sandbox import approvals, task_grants
from skills.github import api, credentials, gh_cli
from skills.github import tools as gh_tools
from skills.shell_runner import tools as _shell_runner  # noqa: F401  (loaded before subprocess.run is patched)

FAKE = "aigator-fake-api-key"
CLASSIC_PAT_BLOCKED = (
    '{"message":"The \'ROCm\' organization forbids access via a personal access token (classic). '
    'Please use a fine-grained personal access token."}'
)


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


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


def _rest_returns(monkeypatch, code=None, payload=None, body=CLASSIC_PAT_BLOCKED):
    seen = []

    def urlopen(req, timeout=None):
        seen.append(req.full_url)
        if code is None:
            return _Resp(payload)
        raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(body.encode()))

    monkeypatch.setattr(api.urllib.request, "urlopen", urlopen)
    return seen


def _gh_returns(monkeypatch, stdout="", stderr="", exit_code=0, logged_in=True):
    seen = []

    def run(cmd, **kw):
        if cmd[1:3] == ["auth", "status"]:
            return subprocess.CompletedProcess(cmd, 0 if logged_in else 1, "", "")
        seen.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, exit_code, stdout, stderr)

    monkeypatch.setattr(gh_cli.subprocess, "run", run)
    monkeypatch.setattr(gh_cli.shutil, "which", lambda name: "/usr/bin/gh")
    return seen


def test_blocked_token_retries_the_same_get_through_gh(monkeypatch):
    _rest_returns(monkeypatch, code=403)
    calls = _gh_returns(monkeypatch, stdout='{"number": 482, "title": "fix"}')

    result = api._rest("/repos/ROCm/rocm-systems/pulls/482")

    assert result == {"number": 482, "title": "fix"}
    assert calls[0][0] == ["/usr/bin/gh", "api", "repos/ROCm/rocm-systems/pulls/482"]
    assert "GH_TOKEN" not in calls[0][1]["env"]


def test_gh_list_output_is_not_cut_at_the_tool_output_limit(monkeypatch):
    _rest_returns(monkeypatch, code=403)
    big = json.dumps([{"filename": f"src/file_{i}.cpp", "patch": "x" * 500} for i in range(100)])
    assert len(big) > gh_cli._MAX_OUTPUT
    _gh_returns(monkeypatch, stdout=big)

    assert len(api._rest("/repos/o/r/pulls/1/files?per_page=100&page=1")) == 100


def test_healthy_token_never_starts_gh(monkeypatch):
    _rest_returns(monkeypatch, payload={"number": 1})
    monkeypatch.setattr(gh_cli.subprocess, "run", lambda *a, **k: pytest.fail("gh must not run"))
    assert api._rest("/repos/o/r/pulls/1") == {"number": 1}


@pytest.mark.parametrize("code", [404, 422, 500])
def test_other_failures_do_not_fall_back(monkeypatch, code):
    _rest_returns(monkeypatch, code=code, body="nope")
    monkeypatch.setattr(gh_cli.subprocess, "run", lambda *a, **k: pytest.fail("gh must not run"))
    assert api._rest("/repos/o/r/pulls/1")["error"].startswith(f"GitHub API {code}")


def test_writes_never_fall_back(monkeypatch):
    _rest_returns(monkeypatch, code=403)
    monkeypatch.setattr(gh_cli.subprocess, "run", lambda *a, **k: pytest.fail("gh must not run"))
    result = api._rest("/repos/o/r/issues", method="POST", body={"title": "t"})
    assert result["error"].startswith("GitHub API 403")


def test_gh_not_signed_in_does_not_retry_with_the_same_saved_token(monkeypatch):
    _rest_returns(monkeypatch, code=403)
    calls = _gh_returns(monkeypatch, logged_in=False)

    result = api._rest("/repos/ROCm/rocm-systems/pulls/482")

    assert calls == []
    assert "GitHub API 403" in result["error"] and "gh auth login" in result["error"]


def test_gh_also_refused_explains_how_to_authorize_the_org(monkeypatch):
    _rest_returns(monkeypatch, code=403)
    _gh_returns(monkeypatch, exit_code=1,
                stderr="HTTP 403: Resource protected by organization SAML enforcement. (https://api.github.com/x)")

    result = api._rest("/repos/ROCm/rocm-systems/pulls/482")

    assert "forbids access via a personal access token" in result["error"]
    assert "SAML enforcement" in result["error"]
    assert "https://github.com/orgs/ROCm/sso" in result["error"]


def test_unparseable_gh_output_is_reported_not_raised(monkeypatch):
    _rest_returns(monkeypatch, code=403)
    _gh_returns(monkeypatch, stdout="not json")
    assert "error" in api._rest("/repos/o/r/pulls/1")


def test_paginated_lists_work_through_the_fallback(monkeypatch):
    _rest_returns(monkeypatch, code=403)
    calls = _gh_returns(monkeypatch, stdout='[{"id": 1}]')
    assert api._rest_list("/repos/o/r/pulls/1/reviews") == [{"id": 1}]
    assert calls[0][0][2] == "repos/o/r/pulls/1/reviews?per_page=100&page=1"


def test_get_pr_returns_the_slim_shape_through_gh(monkeypatch):
    _rest_returns(monkeypatch, code=403)

    def run(cmd, **kw):
        if cmd[1:3] == ["auth", "status"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        path = cmd[2].split("?")[0]
        out = {
            "repos/ROCm/rocm-systems/pulls/482": {"number": 482, "title": "t", "state": "open",
                                                  "head": {"ref": "b", "sha": "abc"}},
            "repos/ROCm/rocm-systems/commits/abc/check-runs": {"check_runs": [{"name": "ci", "status": "completed",
                                                                                 "conclusion": "success"}]},
        }.get(path, [])
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")

    monkeypatch.setattr(gh_cli.subprocess, "run", run)
    monkeypatch.setattr(gh_cli.shutil, "which", lambda name: "/usr/bin/gh")

    pr = gh_tools._github_get_pr("ROCm", "rocm-systems", 482)

    assert pr["number"] == 482 and pr["head"] == {"ref": "b"}
    assert pr["checks_summary"] == {"success": 1}


def test_get_pr_stops_after_the_first_failure(monkeypatch):
    seen = _rest_returns(monkeypatch, code=404, body="Not Found")
    result = gh_tools._github_get_pr("o", "r", 1)
    assert "error" in result and len(seen) == 1
