"""Pins the stdio process pool's keying and eviction for servers configured without a cwd.

Adding an optional cwd to the launch config must not change any of this.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "web"))

import pytest

from mcp import stdio_client as sc


@pytest.fixture(autouse=True)
def _clean_pool(monkeypatch):
    monkeypatch.setattr(sc, "_pool", {})
    monkeypatch.setattr(sc, "_run_preflight", lambda cfg: None)


class _Fake:
    def __init__(self, cfg, timeout=30.0):
        self.cfg = cfg
        self._proc = MagicMock()
        self._proc.poll.return_value = None
        self.closed = False

    def close(self):
        self.closed = True


def _cfg(**over):
    cfg = {"name": "srv", "command": "python", "args": ["a.py"], "env": {"K": "v"}}
    cfg.update(over)
    return cfg


def test_pool_key_is_command_args_and_env_only():
    key = sc._pool_key(_cfg())
    assert key == ("python", ("a.py",), frozenset({("K", "v")}))


def test_pool_key_ignores_the_connection_name():
    assert sc._pool_key(_cfg(name="one")) == sc._pool_key(_cfg(name="two"))


def test_same_config_shares_one_process_and_release_evicts_it(monkeypatch):
    monkeypatch.setattr(sc, "StdioMCPClient", _Fake)

    first = sc.acquire_pooled(_cfg())
    assert sc.acquire_pooled(_cfg()) is first

    sc.release_from_pool({"command": "python", "args": ["a.py"], "env": {"K": "v"}, "name": "srv"})

    assert first.closed is True
    assert sc.acquire_pooled(_cfg()) is not first


def test_release_with_a_different_config_leaves_the_process_running(monkeypatch):
    monkeypatch.setattr(sc, "StdioMCPClient", _Fake)
    first = sc.acquire_pooled(_cfg())

    sc.release_from_pool(_cfg(args=["other.py"]))

    assert first.closed is False
