import subprocess

import pytest

from skills.github import credentials, gh_cli
from skills.github import tools as gh_tools

FAKE = "aigator-fake-api-key"


@pytest.fixture(autouse=True)
def _no_saved_config(monkeypatch):
    monkeypatch.setattr(credentials, "_saved", lambda: {})
    for var in ("GITHUB_TOKEN", "GITHUB_BASE_URL", "GH_TOKEN"):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.parametrize("args", [
    ["issue", "list"],
    ["pr", "checks", "92", "-R", "owner/repo"],
    ["label", "list", "--repo=owner/repo"],
    ["run", "rerun", "123", "--failed"],
    ["pr", "view", "https://github.com/owner/repo/pull/1"],
    ["api", "repos/owner/repo/labels", "--jq", ".[].name", "--paginate"],
    ["api", "-X", "GET", "user"],
    ["status"],
])
def test_allowed_commands(args):
    assert gh_cli.validate(args) is None


@pytest.mark.parametrize("args", [
    [],
    "pr list",
    ["auth", "token"],
    ["extension", "install", "x/y"],
    ["alias", "set", "a", "!rm -rf ~"],
    ["pr", "merge", "1"],
    ["pr"],
    ["repo", "delete", "owner/repo"],
    ["label", "delete", "bug"],
    ["issue", "create", "--body-file", "C:/Users/me/.ssh/id_rsa"],
    ["issue", "create", "--body-file=notes.txt"],
    ["issue", "comment", "1", "-F", "notes.txt"],
    ["issue", "list", "--web"],
    ["issue", "list", "-R", "evil.example/owner/repo"],
    ["issue", "list", "--repo", "not a repo"],
    ["pr", "view", "https://evil.example/owner/repo/pull/1"],
    ["pr", "view", "http://github.com/owner/repo/pull/1"],
    ["api", "-X", "DELETE", "repos/owner/repo"],
    ["api", "--method=POST", "repos/owner/repo/issues"],
    ["api", "graphql", "-f", "query={viewer{login}}"],
    ["api", "user", "--hostname", "evil.example"],
    ["api", "user", "--input", "secrets.json"],
    ["api", "user", "-H", "Authorization: token x"],
    ["api", "https://evil.example/user"],
    ["issue", "list", "bad\0arg"],
])
def test_refused_commands(args):
    assert gh_cli.validate(args)


def test_enterprise_host_urls_are_allowed(monkeypatch):
    monkeypatch.setattr(credentials, "_saved", lambda: {"github_base_url": "https://ghe.example.com"})
    assert gh_cli.validate(["pr", "view", "https://ghe.example.com/o/r/pull/1"]) is None
    assert gh_cli.validate(["pr", "view", "https://other.example.com/o/r/pull/1"])


def _fake_run(monkeypatch, logged_in, record):
    def run(cmd, **kw):
        record.append((cmd, kw))
        if cmd[1:3] == ["auth", "status"]:
            return subprocess.CompletedProcess(cmd, 0 if logged_in else 1, b"", b"")
        return subprocess.CompletedProcess(cmd, 0, f"ok {FAKE}", "")

    monkeypatch.setattr(gh_cli.subprocess, "run", run)
    monkeypatch.setattr(gh_cli.shutil, "which", lambda name: "/usr/bin/gh")


def test_uses_the_users_own_login_and_strips_token_variables(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "from-parent-env")
    monkeypatch.setattr(credentials, "_saved", lambda: {"github_token": FAKE})
    calls = []
    _fake_run(monkeypatch, True, calls)

    result = gh_cli.run_gh(["issue", "list"])

    assert result["auth"] == "gh login" and result["exit_code"] == 0
    for _, kw in calls:
        assert not {"GITHUB_TOKEN", "GH_TOKEN", "GH_ENTERPRISE_TOKEN"} & set(kw["env"])
        assert kw["stdin"] == subprocess.DEVNULL
    assert calls[-1][0] == ["/usr/bin/gh", "issue", "list"]


def test_falls_back_to_the_saved_token_for_this_process_only(monkeypatch):
    monkeypatch.setattr(credentials, "_saved", lambda: {"github_token": FAKE})
    calls = []
    _fake_run(monkeypatch, False, calls)

    result = gh_cli.run_gh(["issue", "list"])

    assert result["auth"] == "saved GitHub token"
    assert calls[-1][1]["env"]["GH_TOKEN"] == FAKE
    assert FAKE not in result["stdout"]
    import os
    assert "GH_TOKEN" not in os.environ


def test_enterprise_fallback_uses_enterprise_variable_and_host(monkeypatch):
    monkeypatch.setattr(credentials, "_saved", lambda: {"github_token": FAKE, "github_base_url": "https://ghe.example.com"})
    calls = []
    _fake_run(monkeypatch, False, calls)

    gh_cli.run_gh(["issue", "list"])

    env = calls[-1][1]["env"]
    assert env["GH_ENTERPRISE_TOKEN"] == FAKE and env["GH_HOST"] == "ghe.example.com"
    assert "GH_TOKEN" not in env


def test_not_signed_in_and_no_token_says_how_to_fix(monkeypatch):
    calls = []
    _fake_run(monkeypatch, False, calls)
    result = gh_cli.run_gh(["issue", "list"])
    assert "Settings" in result["error"] and len(calls) == 1


def test_missing_gh_points_to_the_github_tools(monkeypatch):
    monkeypatch.setattr(gh_cli.shutil, "which", lambda name: None)
    assert "github_*" in gh_cli.run_gh(["issue", "list"])["error"]


def test_refused_command_never_starts_a_process(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not run")

    monkeypatch.setattr(gh_cli.subprocess, "run", boom)
    assert "error" in gh_cli.run_gh(["auth", "token"])


def test_nonzero_exit_reports_stderr(monkeypatch):
    monkeypatch.setattr(gh_cli.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(gh_cli.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0 if cmd[1:3] == ["auth", "status"] else 1, "", "HTTP 404"))
    result = gh_cli.run_gh(["issue", "view", "9"])
    assert result["exit_code"] == 1 and "HTTP 404" in result["error"]


def test_tool_is_registered():
    assert "github_gh" in gh_tools.TOOL_HANDLERS
    assert "github_gh" in {t["name"] for t in gh_tools.TOOL_DEFS}


def test_saved_token_wins_over_environment_and_env_is_a_fallback(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")
    assert credentials.get_token() == "from-env"
    monkeypatch.setattr(credentials, "_saved", lambda: {"github_token": FAKE})
    assert credentials.get_token() == FAKE


def test_saving_github_credentials_does_not_export_the_token(monkeypatch):
    import os
    from web.routes import config_routes

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"login": "someone"}'

    saved = {}
    monkeypatch.setattr(config_routes.urllib.request, "urlopen", lambda *a, **k: _Resp())
    monkeypatch.setattr(config_routes, "_load_config", lambda: {})
    monkeypatch.setattr(config_routes, "_save_config", saved.update)

    out = config_routes.save_github(config_routes.GithubConfigRequest(token=FAKE, url="github.com"))

    assert out["user"] == "someone" and saved["github_token"] == FAKE
    assert "GITHUB_TOKEN" not in os.environ and "GITHUB_BASE_URL" not in os.environ
