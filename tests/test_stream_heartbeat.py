"""Unit tests for the visible SSE heartbeat helper in routes.chat.

The chat SSE stream already emits an invisible `: ping` keepalive comment
every 15s of silence. `_heartbeat_status` decides when that same 15s-tick
loop should ALSO surface a visible `{"status": ...}` chunk, so a long-running
tool call doesn't look frozen in the UI. This tests the pure helper only —
no async/timeout driving needed.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web'))

from routes.chat import _heartbeat_status


def test_stays_quiet_below_threshold():
    assert _heartbeat_status(0) is None
    assert _heartbeat_status(1) is None
    assert _heartbeat_status(2) is None


def test_first_heartbeat_at_threshold():
    assert _heartbeat_status(3) == "Still working... (45s)"


def test_quiet_immediately_after_first_heartbeat():
    assert _heartbeat_status(4) is None


def test_cadence_of_subsequent_heartbeats():
    assert _heartbeat_status(5) == "Still working... (75s)"
    assert _heartbeat_status(6) is None
    assert _heartbeat_status(7) == "Still working... (105s)"


def test_respects_custom_interval_seconds():
    assert _heartbeat_status(3, interval_seconds=10) == "Still working... (30s)"
