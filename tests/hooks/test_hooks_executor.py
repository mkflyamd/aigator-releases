import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'web'))

import json
from pathlib import Path


def test_fire_hook_runs_command_and_allows_on_exit_0(tmp_path):
    hooks_json = {"hooks": [{"event": "PreToolUse", "command": "exit 0"}]}
    (tmp_path / "hooks.json").write_text(json.dumps(hooks_json))

    from hooks.executor import fire_event
    result = fire_event("PreToolUse", tmp_path)
    assert result["blocked"] is False


def test_fire_hook_blocks_on_nonzero_exit(tmp_path):
    hooks_json = {"hooks": [{"event": "PreToolUse", "command": "exit 1"}]}
    (tmp_path / "hooks.json").write_text(json.dumps(hooks_json))

    from hooks.executor import fire_event
    result = fire_event("PreToolUse", tmp_path)
    assert result["blocked"] is True


def test_fire_hook_only_runs_matching_event(tmp_path):
    hooks_json = {"hooks": [
        {"event": "BeforeEmailSend", "command": "exit 1"},
        {"event": "PreToolUse", "command": "exit 0"},
    ]}
    (tmp_path / "hooks.json").write_text(json.dumps(hooks_json))

    from hooks.executor import fire_event
    result = fire_event("PreToolUse", tmp_path)
    assert result["blocked"] is False  # only the PreToolUse hook ran


def test_fire_hook_noop_when_no_hooks_json(tmp_path):
    from hooks.executor import fire_event
    result = fire_event("PreToolUse", tmp_path)
    assert result["blocked"] is False


def test_fire_hook_noop_when_no_matching_event(tmp_path):
    hooks_json = {"hooks": [{"event": "AfterAgentComplete", "command": "exit 1"}]}
    (tmp_path / "hooks.json").write_text(json.dumps(hooks_json))

    from hooks.executor import fire_event
    result = fire_event("PreToolUse", tmp_path)
    assert result["blocked"] is False


def test_before_email_send_event_constant():
    from hooks.events import BEFORE_EMAIL_SEND, BEFORE_TEAMS_MESSAGE, BEFORE_SLACK_MESSAGE
    assert BEFORE_EMAIL_SEND == "BeforeEmailSend"
    assert BEFORE_TEAMS_MESSAGE == "BeforeTeamsMessage"
    assert BEFORE_SLACK_MESSAGE == "BeforeSlackMessage"


def test_fire_hook_fails_closed_on_subprocess_crash(tmp_path, monkeypatch):
    """If subprocess.run raises (e.g. OSError from a bad command), the send
    must be blocked — never allowed by default. CLAUDE.md: email/Teams/Slack
    must never auto-send without explicit approval."""
    hooks_json = {"hooks": [{"event": "BeforeEmailSend", "command": "anything"}]}
    (tmp_path / "hooks.json").write_text(json.dumps(hooks_json))

    import subprocess
    def boom(*a, **kw):
        raise OSError("simulated crash")
    monkeypatch.setattr(subprocess, "run", boom)

    from hooks.executor import fire_event
    result = fire_event("BeforeEmailSend", tmp_path)
    assert result["blocked"] is True
    assert "hook error" in result["reason"]


def test_fire_hook_blocks_on_timeout(tmp_path, monkeypatch):
    """TimeoutExpired must block — a stuck hook shouldn't be interpreted as approval."""
    hooks_json = {"hooks": [{"event": "BeforeEmailSend", "command": "sleep 999"}]}
    (tmp_path / "hooks.json").write_text(json.dumps(hooks_json))

    import subprocess
    def timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="x", timeout=30)
    monkeypatch.setattr(subprocess, "run", timeout)

    from hooks.executor import fire_event
    result = fire_event("BeforeEmailSend", tmp_path)
    assert result["blocked"] is True
    assert "timed out" in result["reason"]


def test_fire_hook_strips_gateway_credentials_from_subprocess_env(tmp_path, monkeypatch):
    """AMD gateway key, NTID, and gateway URL must NOT be visible to author-supplied
    hook commands — otherwise a malicious plugin could exfiltrate them. CLAUDE.md:
    'Non-compliance results in service disruption (gateway access revoked).'"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-key")
    monkeypatch.setenv("GATEWAY_USER_ID", "secret-ntid")
    monkeypatch.setenv("LLM_GATEWAY_URL", "https://llm-api.amd.com/Anthropic")
    monkeypatch.setenv("SAFE_VAR", "visible")

    import subprocess
    captured = {}
    real_run = subprocess.run
    def capture(*a, **kw):
        captured["env"] = kw.get("env")
        # Return a successful run so the assertion path is clear
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()
    monkeypatch.setattr(subprocess, "run", capture)

    hooks_json = {"hooks": [{"event": "BeforeEmailSend", "command": "env"}]}
    (tmp_path / "hooks.json").write_text(json.dumps(hooks_json))

    from hooks.executor import fire_event
    fire_event("BeforeEmailSend", tmp_path)

    env = captured["env"]
    assert env is not None, "fire_event must pass env= to subprocess.run (not inherit parent env)"
    assert "ANTHROPIC_API_KEY" not in env
    assert "GATEWAY_USER_ID" not in env
    assert "LLM_GATEWAY_URL" not in env
    # Sanity: unrelated env vars still pass through so hooks aren't crippled
    assert env.get("SAFE_VAR") == "visible"


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


def test_fire_all_skill_hooks_resolves_hooks_json_at_skill_root(tmp_path, monkeypatch):
    """Regression: skill_dir passed to fire_event must be the skill root, NOT
    a hooks/ subdirectory — otherwise fire_event resolves hooks.json one level
    too deep and silently no-ops every hook."""
    skill_root = tmp_path / "cache" / "my-marketplace" / "blocker-skill" / "1.0.0"
    skill_root.mkdir(parents=True)
    (skill_root / "hooks.json").write_text(json.dumps({
        "hooks": [{"event": "BeforeEmailSend", "command": "exit 1"}]
    }))

    import config
    monkeypatch.setattr(config, "PLUGINS_DIR", tmp_path)

    from marketplace import installer
    monkeypatch.setattr(installer, "load_installed", lambda: [
        {"id": "blocker-skill", "source": "my-marketplace", "version": "1.0.0"}
    ])

    from hooks.executor import fire_all_skill_hooks
    result = fire_all_skill_hooks("BeforeEmailSend")
    assert result["blocked"] is True, "hooks.json at skill root must be discovered"


def test_fire_all_skill_hooks_runs_for_plugin_without_tools_py(tmp_path, monkeypatch):
    """Regression: a plugin shipping hooks.json without tools.py must still
    have its hooks fired. Iterating INSTALLED_TOOL_MODULES would skip these
    (they're never registered there) and silently bypass a compliance plugin."""
    skill_root = tmp_path / "cache" / "mp" / "hooks-only" / "1.0.0"
    skill_root.mkdir(parents=True)
    (skill_root / "hooks.json").write_text(json.dumps({
        "hooks": [{"event": "BeforeTeamsMessage", "command": "exit 1"}]
    }))
    # Deliberately no tools.py — and no entry in INSTALLED_TOOL_MODULES

    import config, shared
    monkeypatch.setattr(config, "PLUGINS_DIR", tmp_path)
    monkeypatch.setattr(shared, "INSTALLED_TOOL_MODULES", {})

    from marketplace import installer
    monkeypatch.setattr(installer, "load_installed", lambda: [
        {"id": "hooks-only", "source": "mp", "version": "1.0.0"}
    ])

    from hooks.executor import fire_all_skill_hooks
    result = fire_all_skill_hooks("BeforeTeamsMessage")
    assert result["blocked"] is True, "hooks-only plugins must not be silently skipped"
