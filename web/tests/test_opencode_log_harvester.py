"""Tests for the OpenCode connectivity/stream-error log harvester (issue #156).

The harvester tails OpenCode's own structured log and mirrors stream/connection
failures into AiGator's server log — the reliable replacement for the earlier
client-side TUI-text beacon, which missed error shapes like GatewayTimeout.
"""
import importlib
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # web/

import pytest

STREAM_ERR = (
    'timestamp=2026-07-27T02:28:47Z level=ERROR run=ddd message="stream error" '
    'providerID=gator-gateway modelID=GLM-5.2-FP8 session.id=ses_072 small=false '
    'agent=build mode=primary error.error="AI_APICallError: OnPremLLM returned '
    'GatewayTimeout. Reason: stream timeout"\n'
)
MODELS_DEV = (
    'timestamp=2026-07-27T02:29:00Z level=ERROR run=ddd '
    'message="Failed to fetch models.dev" cause="Transport error"\n'
)
INFO_LINE = (
    'timestamp=2026-07-27T02:29:05Z level=INFO run=ddd message="loop" session.id=ses_072\n'
)


@pytest.fixture
def harvester(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    logdir = tmp_path / "opencode" / "log"
    logdir.mkdir(parents=True)
    logpath = logdir / "opencode.log"
    from skills.opencode_agent import log_harvester
    importlib.reload(log_harvester)  # reset module-level _offset per test
    return log_harvester, logpath


def test_init_offset_skips_backlog(harvester):
    h, logpath = harvester
    logpath.write_text(STREAM_ERR * 5, encoding="utf-8")
    h.init_offset()
    # Historical errors present before startup must NOT be replayed.
    assert h.harvest_stream_errors() == 0


def test_surfaces_new_stream_and_models_dev_errors(harvester, caplog):
    h, logpath = harvester
    logpath.write_text("", encoding="utf-8")
    h.init_offset()
    with logpath.open("a", encoding="utf-8") as f:
        f.write(STREAM_ERR)
        f.write(MODELS_DEV)
        f.write(INFO_LINE)  # non-error, must be ignored
    with caplog.at_level(logging.WARNING):
        n = h.harvest_stream_errors()
    assert n == 2, "should surface the stream error + models.dev, not the INFO line"
    joined = "\n".join(caplog.messages)
    assert "kind=api" in joined and "GLM-5.2-FP8" in joined and "GatewayTimeout" in joined
    assert "kind=models.dev" in joined


def test_idempotent_when_no_new_content(harvester):
    h, logpath = harvester
    logpath.write_text("", encoding="utf-8")
    h.init_offset()
    logpath.open("a", encoding="utf-8").write(STREAM_ERR)
    assert h.harvest_stream_errors() == 1
    assert h.harvest_stream_errors() == 0  # nothing new


def test_handles_truncation_rotation(harvester):
    h, logpath = harvester
    logpath.write_text(STREAM_ERR * 3, encoding="utf-8")
    h.init_offset()  # offset at end
    # File rotated/truncated to something smaller than the current offset.
    logpath.write_text(STREAM_ERR, encoding="utf-8")
    assert h.harvest_stream_errors() == 1, "must reset offset and read the new file"


def test_missing_log_file_is_noop(harvester):
    h, logpath = harvester
    # No file created at all.
    assert not logpath.exists()
    h.init_offset()
    assert h.harvest_stream_errors() == 0
