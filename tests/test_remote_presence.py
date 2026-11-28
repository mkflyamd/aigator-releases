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
    assert presence.is_away() is False


def test_other_platforms_are_never_away(monkeypatch):
    monkeypatch.setattr(presence.sys, "platform", "linux")
    probes(monkeypatch, locked=True, idle=9999)
    assert presence.is_away() is False


@pytest.mark.skipif(not presence.sys.platform.startswith("win"), reason="Windows desktop probes")
def test_the_real_probes_answer_on_this_machine():
    assert presence._screen_locked() in (True, False)
    assert presence._idle_seconds() >= 0
