import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "web"))

import json
from pathlib import Path

import sandbox


def _hooks(make_skill_dir, hooks: list[dict]) -> Path:
    return make_skill_dir({"hooks.json": json.dumps({"hooks": hooks})})


def _result(returncode=0, stdout="", stderr="", timed_out=False):
    return sandbox.SandboxResult(returncode=returncode, stdout=stdout, stderr=stderr, timed_out=timed_out)


def test_fire_hook_allows_on_exit_0(make_skill_dir, fake_sandbox):
    skill = _hooks(make_skill_dir, [{"event": "PreToolUse", "command": "exit 0"}])

    from hooks.executor import fire_event

    assert fire_event("PreToolUse", skill)["blocked"] is False
    assert len(fake_sandbox.requests) == 1


def test_fire_hook_blocks_on_nonzero_exit_and_reports_stderr(make_skill_dir, fake_sandbox):
    skill = _hooks(make_skill_dir, [{"event": "PreToolUse", "command": "exit 1"}])
    fake_sandbox.result = _result(returncode=1, stderr="needs approval\n")

    from hooks.executor import fire_event

    result = fire_event("PreToolUse", skill)
    assert result["blocked"] is True
    assert result["reason"] == "needs approval"


def test_fire_hook_reason_falls_back_to_stdout_then_exit_code(make_skill_dir, fake_sandbox):
    skill = _hooks(make_skill_dir, [{"event": "PreToolUse", "command": "x"}])

    from hooks.executor import fire_event

    fake_sandbox.result = _result(returncode=2, stdout="from stdout")
    assert fire_event("PreToolUse", skill)["reason"] == "from stdout"
    fake_sandbox.result = _result(returncode=2)
    assert fire_event("PreToolUse", skill)["reason"] == "exit 2"


def test_fire_hook_only_runs_matching_event(make_skill_dir, fake_sandbox):
    skill = _hooks(
        make_skill_dir,
        [
            {"event": "BeforeEmailSend", "command": "exit 1"},
            {"event": "PreToolUse", "command": "exit 0"},
        ],
    )

    from hooks.executor import fire_event

    result = fire_event("PreToolUse", skill)
    assert result["blocked"] is False
    assert len(fake_sandbox.requests) == 1  # only the PreToolUse hook ran


def test_fire_hook_noop_when_no_hooks_json(make_skill_dir, fake_sandbox):
    skill = make_skill_dir({"SKILL.md": "x"})

    from hooks.executor import fire_event

    assert fire_event("PreToolUse", skill)["blocked"] is False
    assert fake_sandbox.requests == []


def test_fire_hook_noop_when_no_matching_event(make_skill_dir, fake_sandbox):
    skill = _hooks(make_skill_dir, [{"event": "AfterAgentComplete", "command": "exit 1"}])

    from hooks.executor import fire_event

    assert fire_event("PreToolUse", skill)["blocked"] is False
    assert fake_sandbox.requests == []


def test_malformed_hooks_json_still_allows(make_skill_dir, fake_sandbox):
    skill = make_skill_dir({"hooks.json": "{not json"})

    from hooks.executor import fire_event

    assert fire_event("BeforeEmailSend", skill)["blocked"] is False


def test_before_email_send_event_constant():
    from hooks.events import (
        BEFORE_EMAIL_SEND,
        BEFORE_TEAMS_MESSAGE,
        BEFORE_SLACK_MESSAGE,
    )

    assert BEFORE_EMAIL_SEND == "BeforeEmailSend"
    assert BEFORE_TEAMS_MESSAGE == "BeforeTeamsMessage"
    assert BEFORE_SLACK_MESSAGE == "BeforeSlackMessage"


def test_fire_hook_fails_closed_when_the_sandbox_cannot_start(make_skill_dir, fake_sandbox):
    """A sandbox failure must block the send, never allow it or run the hook unsandboxed.
    CLAUDE.md: email/Teams/Slack must never auto-send without explicit approval."""
    skill = _hooks(make_skill_dir, [{"event": "BeforeEmailSend", "command": "anything"}])

    from hooks.executor import fire_event

    for exc in (sandbox.SandboxUnavailable("no sandbox"), sandbox.SandboxRunError("boom"), OSError("simulated")):
        fake_sandbox.raises = exc
        result = fire_event("BeforeEmailSend", skill)
        assert result["blocked"] is True
        assert "hook error" in result["reason"]


def test_fire_hook_blocks_on_timeout(make_skill_dir, fake_sandbox):
    """A stuck hook shouldn't be interpreted as approval."""
    skill = _hooks(make_skill_dir, [{"event": "BeforeEmailSend", "command": "sleep 999"}])
    fake_sandbox.result = _result(returncode=-1, timed_out=True)

    from hooks.executor import fire_event

    result = fire_event("BeforeEmailSend", skill)
    assert result["blocked"] is True
    assert "timed out" in result["reason"]
    assert fake_sandbox.requests[0].timeout == 30


def test_fire_hook_environment_has_no_gateway_credentials(make_skill_dir, fake_sandbox, monkeypatch):
    """AMD gateway key, NTID, and gateway URL must NOT be visible to author-supplied
    hook commands. The sandbox environment is built by sandbox.build_env."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "aigator-fake-api-key")
    monkeypatch.setenv("GATEWAY_USER_ID", "aigator-fake-api-key")
    monkeypatch.setenv("LLM_GATEWAY_URL", "https://llm-api.example.com/Anthropic")
    skill = _hooks(make_skill_dir, [{"event": "BeforeEmailSend", "command": "env"}])

    from hooks.executor import fire_event

    fire_event("BeforeEmailSend", skill)
    env = fake_sandbox.requests[0].env
    assert "ANTHROPIC_API_KEY" not in env
    assert "GATEWAY_USER_ID" not in env
    assert "LLM_GATEWAY_URL" not in env
    assert not any("aigator-fake-api-key" in str(v) for v in env.values())


from unittest.mock import patch


def test_send_email_fires_before_email_send_hook():
    """_tool_send_email must call fire_all_skill_hooks with BEFORE_EMAIL_SEND."""
    with patch("skills.email.tools.fire_all_skill_hooks") as mock_fire:
        mock_fire.return_value = {"blocked": False, "reason": ""}
        from skills.email.tools import _tool_send_email

        _tool_send_email(to="a@b.com", subject="Hi", body="Hello")
        mock_fire.assert_called_once()
        call_args = mock_fire.call_args[0]
        assert call_args[0] == "BeforeEmailSend"


def test_send_email_aborts_when_hook_blocks():
    with patch("skills.email.tools.fire_all_skill_hooks") as mock_fire:
        mock_fire.return_value = {"blocked": True, "reason": "requires approval"}
        from skills.email.tools import _tool_send_email

        result = _tool_send_email(to="a@b.com", subject="Hi", body="Hello")
        # Assert the dict contract callers depend on, not just substring match
        assert result["status"] == "blocked"
        assert "approval" in result["reason"]


def test_fire_all_skill_hooks_resolves_hooks_json_at_skill_root(tmp_path, monkeypatch, fake_sandbox):
    """Regression: skill_dir passed to fire_event must be the skill root, NOT
    a hooks/ subdirectory — otherwise fire_event resolves hooks.json one level
    too deep and silently no-ops every hook."""
    skill_root = tmp_path / "cache" / "my-marketplace" / "blocker-skill" / "1.0.0"
    skill_root.mkdir(parents=True)
    (skill_root / "hooks.json").write_text(
        json.dumps({"hooks": [{"event": "BeforeEmailSend", "command": "exit 1"}]})
    )
    fake_sandbox.result = _result(returncode=1)

    import config

    monkeypatch.setattr(config, "PLUGINS_DIR", tmp_path)

    from marketplace import installer

    monkeypatch.setattr(
        installer,
        "load_installed",
        lambda: [
            {"id": "blocker-skill", "source": "my-marketplace", "version": "1.0.0"}
        ],
    )

    from hooks.executor import fire_all_skill_hooks

    result = fire_all_skill_hooks("BeforeEmailSend")
    assert result["blocked"] is True, "hooks.json at skill root must be discovered"
    assert fake_sandbox.requests[0].runtime_paths  # the skill folder is readable inside the sandbox


def test_fire_all_skill_hooks_runs_for_plugin_without_tools_py(tmp_path, monkeypatch, fake_sandbox):
    """Regression: a plugin shipping hooks.json without tools.py must still
    have its hooks fired. Iterating INSTALLED_TOOL_MODULES would skip these
    (they're never registered there) and silently bypass a compliance plugin."""
    skill_root = tmp_path / "cache" / "mp" / "hooks-only" / "1.0.0"
    skill_root.mkdir(parents=True)
    (skill_root / "hooks.json").write_text(
        json.dumps({"hooks": [{"event": "BeforeTeamsMessage", "command": "exit 1"}]})
    )
    fake_sandbox.result = _result(returncode=1)
    # Deliberately no tools.py — and no entry in INSTALLED_TOOL_MODULES

    import config, shared

    monkeypatch.setattr(config, "PLUGINS_DIR", tmp_path)
    monkeypatch.setattr(shared, "INSTALLED_TOOL_MODULES", {})

    from marketplace import installer

    monkeypatch.setattr(
        installer,
        "load_installed",
        lambda: [{"id": "hooks-only", "source": "mp", "version": "1.0.0"}],
    )

    from hooks.executor import fire_all_skill_hooks

    result = fire_all_skill_hooks("BeforeTeamsMessage")
    assert result["blocked"] is True, "hooks-only plugins must not be silently skipped"
