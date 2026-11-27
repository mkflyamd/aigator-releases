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


@pytest.mark.parametrize(
    "text",
    ["not json", "[]", '{"agent_messaging": "no"}', '{"opted_out": 3}', '{"opted_out": [1]}'],
)
def test_settings_that_cannot_be_trusted_turn_messaging_off_and_deny_every_agent(world, text):
    path = settings.settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    assert not settings.user_allows_messaging()
    assert not settings.messaging_allowed()
    assert settings.opted_out("pty:a")


def test_a_settings_file_that_cannot_be_read_turns_messaging_off_and_denies_every_agent(world):
    settings.settings_file().mkdir(parents=True)
    assert not settings.user_allows_messaging()
    assert settings.opted_out("pty:a")


def test_no_settings_file_yet_means_the_defaults(world):
    assert not settings.settings_file().exists()
    assert settings.user_allows_messaging()
    assert not settings.opted_out("pty:a")


def test_opting_an_agent_out_of_a_damaged_file_keeps_messaging_off(world):
    path = settings.settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json")
    settings.set_opted_out("pty:a", True)
    assert not settings.user_allows_messaging()
    assert settings.opted_out("pty:a")


def test_the_users_own_switch_keeps_opt_outs_from_a_partly_valid_file(world):
    path = settings.settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"agent_messaging": "no", "opted_out": ["pty:a", 7]}')
    settings.set_user_messaging(True)
    assert settings.user_allows_messaging()
    assert settings.opted_out("pty:a")
    assert not settings.opted_out("pty:b")


def test_opting_another_agent_out_of_a_partly_valid_file_keeps_the_earlier_opt_outs(world):
    path = settings.settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"agent_messaging": "no", "opted_out": ["pty:a"]}')
    settings.set_opted_out("pty:b", True)
    assert not settings.user_allows_messaging()
    assert settings.opted_out("pty:a")
    assert settings.opted_out("pty:b")


def test_the_users_own_switch_repairs_a_damaged_file(world):
    path = settings.settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json")
    settings.set_user_messaging(True)
    assert settings.user_allows_messaging()
    assert not settings.opted_out("pty:a")


def test_self_chat_autosend_is_off_until_the_user_turns_it_on(world):
    assert settings.admin_allows_self_chat_autosend()
    assert not settings.user_allows_self_chat_autosend()
    assert not settings.self_chat_autosend_allowed()
    settings.set_user_self_chat_autosend(True)
    assert settings.self_chat_autosend_allowed()
    settings.set_user_self_chat_autosend(False)
    assert not settings.self_chat_autosend_allowed()


def test_the_admin_deny_beats_the_users_self_chat_switch(world):
    (world / "sandbox-policy.json").write_text('{"self_chat_autosend": "deny"}')
    settings.set_user_self_chat_autosend(True)
    assert not settings.admin_allows_self_chat_autosend()
    assert not settings.self_chat_autosend_allowed()


def test_a_broken_admin_policy_turns_self_chat_autosend_off(world):
    settings.set_user_self_chat_autosend(True)
    (world / "sandbox-policy.json").write_text("not json")
    assert not settings.self_chat_autosend_allowed()


@pytest.mark.parametrize("text", ["not json", '{"self_chat_autosend": "yes"}', '{"self_chat_autosend": 1}'])
def test_an_untrusted_settings_file_turns_self_chat_autosend_off(world, text):
    path = settings.settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    assert not settings.self_chat_autosend_allowed()


def test_the_self_chat_switch_does_not_turn_agent_messaging_back_on_in_a_damaged_file(world):
    path = settings.settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json")
    settings.set_user_self_chat_autosend(True)
    assert settings.self_chat_autosend_allowed()
    assert not settings.user_allows_messaging()


def test_the_self_chat_switch_keeps_opt_outs_from_a_partly_valid_file(world):
    path = settings.settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"self_chat_autosend": "yes", "opted_out": ["pty:a"]}')
    settings.set_user_self_chat_autosend(True)
    assert settings.opted_out("pty:a")
    assert not settings.user_allows_messaging()


def test_the_self_chat_switch_and_the_messaging_switch_do_not_disturb_each_other(world):
    settings.set_user_self_chat_autosend(True)
    settings.set_user_messaging(False)
    assert settings.self_chat_autosend_allowed()
    settings.set_user_messaging(True)
    settings.set_user_self_chat_autosend(False)
    assert settings.user_allows_messaging()
