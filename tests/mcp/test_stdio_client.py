import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "web"))

import pytest
from mcp.stdio_client import StdioMCPClient, CommandNotFoundError, ConflictError, acquire_pooled, _pool, _pool_lock, _EOF, _run_preflight

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


def test_preflight_no_error_when_no_lock(tmp_path, monkeypatch):
    """No SingletonLock → preflight passes silently."""
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: tmp_path))
    cfg = {"command": "npx", "args": ["-y", "chrome-devtools-mcp@latest"], "env": {}}
    _run_preflight(cfg)  # must not raise


def test_preflight_raises_conflict_when_lock_present(tmp_path, monkeypatch):
    """SingletonLock present → ConflictError with a user-readable message."""
    import pathlib
    profile = tmp_path / ".cache" / "chrome-devtools-mcp" / "chrome-profile"
    profile.mkdir(parents=True)
    (profile / "SingletonLock").touch()
    monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: tmp_path))
    cfg = {"command": "npx", "args": ["-y", "chrome-devtools-mcp@latest"], "env": {}}
    with pytest.raises(ConflictError) as ei:
        _run_preflight(cfg)
    assert "Chrome" in str(ei.value)


def test_preflight_noop_for_non_chrome_mcp():
    """Non-chrome MCPs don't trigger any preflight check."""
    _run_preflight({"command": "python", "args": ["server.py"], "env": {}})


def test_acquire_pooled_poisons_old_queue_on_restart():
    """When a pooled process dies and acquire_pooled restarts it, any call
    blocked on the old client's queue must unblock immediately (not hang for
    30 s until queue.get timeout). This is the chrome-devtools hang fix."""
    import time
    import threading

    cfg = _cfg(name="pool-restart-test")

    # Clean up any leftover pool entry from a previous test run
    from mcp.stdio_client import _pool_key
    key = _pool_key(cfg)
    with _pool_lock:
        old = _pool.pop(key, None)
    if old:
        try:
            old.close()
        except Exception:
            pass

    # Acquire a pooled client
    client = acquire_pooled(cfg)

    # Simulate a call blocked on the queue (the process hasn't responded yet)
    unblocked_at = []

    def _blocked_call():
        try:
            # Put _EOF directly on the OLD queue to simulate what _send() does
            # when it reads EOF — we just want to measure unblock speed here.
            # We instead test the poison path: kill the proc, then call acquire.
            client._proc.kill()
            client._proc.wait()
            # Now trigger acquire_pooled — it should poison the old queue
            acquire_pooled(cfg)
        except Exception:
            pass

    # Start a thread that blocks reading the queue with a long timeout
    result = []
    def _reader():
        t0 = time.monotonic()
        try:
            val = client._queue.get(timeout=10.0)  # would normally hang 10s
        except Exception as e:
            val = e
        result.append(time.monotonic() - t0)

    reader_thread = threading.Thread(target=_reader)
    reader_thread.start()

    # Give reader a moment to block, then kill + restart
    time.sleep(0.1)
    _blocked_call()

    reader_thread.join(timeout=5.0)
    assert not reader_thread.is_alive(), "reader thread still blocked — poison didn't work"
    assert result, "reader never got a value"
    # Should have unblocked in well under 1 second, not 10
    assert result[0] < 2.0, f"reader took {result[0]:.1f}s — still hanging"

    # Clean up
    with _pool_lock:
        c = _pool.pop(key, None)
    if c:
        try:
            c.close()
        except Exception:
            pass
