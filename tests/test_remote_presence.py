"""Away means the screen is locked or the user has had no input for two minutes; a probe that fails means present."""

import pytest

from remote import presence


@pytest.fixture
def on_windows(monkeypatch):
    monkeypatch.setattr(presence.sys, "platform", "win32")


def probes(monkeypatch, locked=False, idle=0.0):
    monkeypatch.setattr(presence, "_screen_locked", lambda: locked)
    monkeypatch.setattr(presence, "_idle_seconds", lambda: idle)


def test_a_locked_screen_is_away(on_windows, monkeypatch):
    probes(monkeypatch, locked=True)
    assert presence.is_away() is True


def test_no_input_for_two_minutes_is_away(on_windows, monkeypatch):
    probes(monkeypatch, idle=presence.AWAY_IDLE_SECONDS)
    assert presence.is_away() is True


def test_recent_input_on_an_unlocked_screen_is_present(on_windows, monkeypatch):
    probes(monkeypatch, idle=presence.AWAY_IDLE_SECONDS - 1)
    assert presence.is_away() is False


def test_a_probe_that_fails_counts_as_present(on_windows, monkeypatch):
    def broken():
        raise OSError("no desktop")

    monkeypatch.setattr(presence, "_screen_locked", broken)
    monkeypatch.setattr(presence, "_idle_seconds", lambda: 0.0)
    assert presence.is_away() is False


def test_a_failed_lock_probe_does_not_hide_a_long_idle(on_windows, monkeypatch):
    def broken():
        raise OSError("no desktop")

    monkeypatch.setattr(presence, "_screen_locked", broken)
    monkeypatch.setattr(presence, "_idle_seconds", lambda: presence.AWAY_IDLE_SECONDS + 1)
    assert presence.is_away() is True


def desktop(monkeypatch, handle, error, idle=60.0):
    closed = []
    monkeypatch.setattr(presence, "_open_input_desktop", lambda: (handle, error))
    monkeypatch.setattr(presence, "_close_desktop", closed.append)
    monkeypatch.setattr(presence, "_idle_seconds", lambda: idle)
    return closed


def test_access_denied_on_the_input_desktop_with_idle_input_is_a_locked_screen(monkeypatch):
    desktop(monkeypatch, None, 5, idle=presence.LOCKED_MIN_IDLE_SECONDS)
    assert presence._screen_locked() is True


def test_access_denied_while_the_user_is_typing_is_not_a_lock(monkeypatch):
    desktop(monkeypatch, None, 5, idle=presence.LOCKED_MIN_IDLE_SECONDS - 1)
    assert presence._screen_locked() is False


@pytest.mark.parametrize("error", [0, 1, 6, 1314, 1450, 87])
def test_any_other_failure_to_open_the_input_desktop_is_not_a_lock(monkeypatch, error):
    desktop(monkeypatch, None, error, idle=3600)
    assert presence._screen_locked() is False


def test_an_open_input_desktop_is_unlocked_and_is_closed_again(monkeypatch):
    closed = desktop(monkeypatch, 1234, 0, idle=3600)
    assert presence._screen_locked() is False
    assert closed == [1234]


@pytest.mark.parametrize("error", [0, 6, 1314])
def test_a_process_that_cannot_see_the_desktop_keeps_the_delay_while_input_is_recent(on_windows, monkeypatch, error):
    desktop(monkeypatch, None, error, idle=30)
    assert presence.is_away() is False


def test_a_locked_screen_makes_is_away_true_through_the_real_probe_path(on_windows, monkeypatch):
    desktop(monkeypatch, None, 5, idle=30)
    assert presence.is_away() is True


def test_other_platforms_are_never_away(monkeypatch):
    monkeypatch.setattr(presence.sys, "platform", "linux")
    probes(monkeypatch, locked=True, idle=9999)
    assert presence.is_away() is False


@pytest.mark.skipif(not presence.sys.platform.startswith("win"), reason="Windows desktop probes")
def test_the_real_probes_answer_on_this_machine():
    assert presence._screen_locked() in (True, False)
    assert presence._idle_seconds() >= 0
