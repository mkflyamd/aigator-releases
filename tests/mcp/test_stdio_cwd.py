"""A stdio connection may carry a working directory. Without one, nothing changes."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "web"))

import pytest

from mcp import manager
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


def _conn(**over):
    conn = {"command": "uv", "args": ["run", "main.py"], "env": {"K": "v"}, "name": "srv", "transport": "stdio"}
    conn.update(over)
    return conn


def test_the_launch_config_has_no_cwd_unless_the_connection_sets_one():
    assert "cwd" not in manager._stdio_cfg(_conn())
    assert manager._stdio_cfg(_conn(cwd="C:/skills/x"))["cwd"] == "C:/skills/x"


def test_the_pool_key_only_changes_when_a_cwd_is_set():
    plain = {"command": "uv", "args": ["a"], "env": {}}

    assert sc._pool_key(plain) == ("uv", ("a",), frozenset())
    assert sc._pool_key({**plain, "cwd": "/x"}) == ("uv", ("a",), frozenset(), "/x")
    assert sc._pool_key({**plain, "cwd": "/x"}) != sc._pool_key({**plain, "cwd": "/y"})


@pytest.mark.parametrize("cwd", [None, "C:/skills/x"])
def test_releasing_a_connection_evicts_exactly_the_process_it_started(monkeypatch, cwd):
    monkeypatch.setattr(sc, "StdioMCPClient", _Fake)
    conn = _conn(**({"cwd": cwd} if cwd else {}))
    client = sc.acquire_pooled(manager._stdio_cfg(conn))

    sc.release_from_pool(manager._stdio_cfg(conn))

    assert client.closed is True


def test_releasing_a_connection_leaves_a_same_command_process_in_another_folder(monkeypatch):
    monkeypatch.setattr(sc, "StdioMCPClient", _Fake)
    first = sc.acquire_pooled(manager._stdio_cfg(_conn(cwd="C:/skills/a")))
    second = sc.acquire_pooled(manager._stdio_cfg(_conn(cwd="C:/skills/b")))

    sc.release_from_pool(manager._stdio_cfg(_conn(cwd="C:/skills/a")))

    assert first.closed is True
    assert second.closed is False


def test_client_for_passes_the_cwd_to_the_pool():
    with patch.object(manager, "acquire_pooled") as acquire:
        manager._client_for(_conn(cwd="C:/skills/x"))

    assert acquire.call_args.args[0]["cwd"] == "C:/skills/x"


def test_client_for_without_a_cwd_builds_the_same_config_as_before():
    with patch.object(manager, "acquire_pooled") as acquire:
        manager._client_for(_conn())

    assert acquire.call_args.args[0] == {
        "command": "uv", "args": ["run", "main.py"], "env": {"K": "v"}, "name": "srv",
    }


@pytest.mark.parametrize("cwd", [None, "C:/skills/x"])
def test_the_process_starts_in_the_cwd_only_when_one_is_set(cwd):
    cfg = {"command": "uv", "args": ["run"], "env": {}, "name": "srv"}
    if cwd:
        cfg["cwd"] = cwd
    client = sc.StdioMCPClient.__new__(sc.StdioMCPClient)
    client._cfg, client._name = cfg, "srv"

    with patch.object(sc.StdioMCPClient, "_resolve_command", return_value="uv"), \
            patch.object(sc.subprocess, "Popen") as popen:
        client._spawn()

    assert popen.call_args.kwargs.get("cwd") == cwd
    assert ("cwd" in popen.call_args.kwargs) is bool(cwd)


@pytest.mark.parametrize("builder", ["_build_connection_record", "_build_disabled_connection"])
def test_the_saved_record_keeps_the_cwd_only_when_set(builder):
    def build(provisional):
        if builder == "_build_connection_record":
            return manager._build_connection_record("id", "n", "stdio", provisional, "", "", [])
        return manager._build_disabled_connection("id", "n", "stdio", provisional, "owner")

    base = {"command": "uv", "args": [], "env": {}}

    assert "cwd" not in build(base)
    assert build({**base, "cwd": "C:/skills/x"})["cwd"] == "C:/skills/x"
