"""What the user and the administrator allow the relay to do."""

import pytest

import agent_suspend
from relay import settings
from sandbox import policy as pol


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_suspend, "STATE_FILE", tmp_path / "suspended-agents.json")
    monkeypatch.setattr(pol, "policy_path", lambda: tmp_path / "sandbox-policy.json")
    monkeypatch.setattr(pol, "_is_posix", lambda: False)
    pol._reset_cache()
    return tmp_path


def test_messaging_is_on_by_default(world):
    assert settings.admin_allows_messaging()
    assert settings.user_allows_messaging()
    assert settings.messaging_allowed()


def test_user_can_switch_messaging_off_and_on(world):
    settings.set_user_messaging(False)
    assert not settings.messaging_allowed()
    settings.set_user_messaging(True)
    assert settings.messaging_allowed()


def test_admin_deny_beats_the_user_switch(world):
    (world / "sandbox-policy.json").write_text('{"agent_messaging": "deny"}')
    settings.set_user_messaging(True)
    assert not settings.admin_allows_messaging()
    assert not settings.messaging_allowed()


def test_a_broken_admin_policy_turns_messaging_off(world):
    (world / "sandbox-policy.json").write_text("not json")
    assert not settings.messaging_allowed()


def test_opt_out_is_per_endpoint(world):
    settings.set_opted_out("pty:a", True)
    settings.set_opted_out("pty:b", True)
    settings.set_opted_out("pty:a", False)
    assert not settings.opted_out("pty:a")
    assert settings.opted_out("pty:b")


def test_opt_out_survives_the_user_switch(world):
    settings.set_opted_out("pty:a", True)
    settings.set_user_messaging(False)
    assert settings.opted_out("pty:a")


@pytest.mark.parametrize("text", ["not json", "[]", '{"agent_messaging": "no", "opted_out": 3}'])
def test_unreadable_settings_fall_back_to_defaults(world, text):
    path = settings.settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    assert settings.user_allows_messaging()
    assert not settings.opted_out("pty:a")
