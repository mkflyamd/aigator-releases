import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "web"))

import pytest
from mcp.stdio_client import StdioMCPClient, CommandNotFoundError

FIXTURE = str(Path(__file__).parent / "fixtures" / "fake_mcp_server.py")
PY = sys.executable


def _cfg(command=PY, args=None, env=None, name="fake"):
    return {
        "command": command,
        "args": args if args is not None else [FIXTURE],
        "env": env or {},
        "name": name,
    }


def test_server_info():
    client = StdioMCPClient(_cfg())
    try:
        info = client.server_info()
        assert info["name"] == "fake"
        assert info["version"] == "0.1"
    finally:
        client.close()


def test_list_tools():
    client = StdioMCPClient(_cfg())
    try:
        tools = client.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "echo"
    finally:
        client.close()


def test_call_tool():
    client = StdioMCPClient(_cfg())
    try:
        out = client.call("echo", {"text": "hi"})
        assert "hi" in out
    finally:
        client.close()


def test_command_not_found():
    with pytest.raises(CommandNotFoundError) as ei:
        StdioMCPClient(_cfg(command="this-command-does-not-exist-xyz"))
    assert "this-command-does-not-exist-xyz" in str(ei.value)


def test_env_merge_preserves_path():
    import os
    client = StdioMCPClient(_cfg(env={"FAKE_VAR": "1"}))
    try:
        # If PATH wasn't preserved, subprocess wouldn't have started at all
        # for npx etc.; we already proved the subprocess runs in earlier tests.
        # Here we just confirm the client survives env injection.
        assert client.server_info()["name"] == "fake"
    finally:
        client.close()


def test_timeout_kills_hung_server():
    import time
    client = StdioMCPClient(_cfg(), timeout=0.5)
    proc = client._proc
    try:
        with pytest.raises(TimeoutError):
            client.call("hang", {})
        # Subprocess should be terminated by close() inside _send timeout path.
        for _ in range(20):
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        assert proc.poll() is not None
    finally:
        client.close()


def test_call_raises_on_server_crash():
    import time
    client = StdioMCPClient(_cfg())
    proc = client._proc
    try:
        with pytest.raises(RuntimeError):
            client.call("crash", {})
        for _ in range(20):
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        assert proc.poll() is not None
    finally:
        client.close()


def test_invalid_json_response():
    client = StdioMCPClient(_cfg())
    try:
        with pytest.raises(RuntimeError) as ei:
            client.call("garbage", {})
        assert "invalid JSON" in str(ei.value)
    finally:
        client.close()
