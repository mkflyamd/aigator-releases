# tests/mcp/test_manager.py
import sys
import threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "web"))

import pytest
from unittest.mock import patch, MagicMock


def _sample_conn(id="mcp-crm", name="CRM", url="http://host/mcp"):
    return {
        "id": id,
        "name": name,
        "url": url,
        "auth_type": "none",
        "auth_value": "",
        "enabled": True,
        "server_info": {"name": name, "version": "1.0"},
        "cached_tools": [
            {
                "name": "crm_get_contact",
                "description": "Get a contact by ID",
                "input_schema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            }
        ],
    }


def test_load_all_from_cache_registers_tools():
    import shared
    from mcp.manager import load_all_from_cache, _unregister

    conn = _sample_conn()
    _unregister(conn["id"])  # clean slate

    with patch("mcp.manager._load_connections", return_value=[conn]):
        load_all_from_cache()

    assert "mcp-crm" in shared.SKILL_TOOLS_MAP
    assert "mcp-crm__crm_get_contact" in shared.TOOL_DISPATCH
    assert any(d["name"] == "mcp-crm__crm_get_contact" for d in shared.TOOLS)
    _unregister(conn["id"])


def test_unregister_removes_tools():
    import shared
    from mcp.manager import load_all_from_cache, _unregister

    conn = _sample_conn()
    _unregister(conn["id"])

    with patch("mcp.manager._load_connections", return_value=[conn]):
        load_all_from_cache()

    assert "mcp-crm__crm_get_contact" in shared.TOOL_DISPATCH
    _unregister("mcp-crm")
    assert "mcp-crm__crm_get_contact" not in shared.TOOL_DISPATCH
    assert "mcp-crm" not in shared.SKILL_TOOLS_MAP


def test_slugify():
    from mcp.manager import _slugify
    assert _slugify("CRM Server") == "crm-server"
    assert _slugify("My  Tool!!") == "my-tool"


def test_add_or_update_connects_and_caches():
    import shared
    from mcp.manager import add_or_update, _unregister

    fake_tools = [
        {"name": "crm_get_contact", "description": "Get contact", "inputSchema": {"type": "object", "properties": {}}}
    ]
    fake_server_info = {"name": "CRM", "version": "1.0"}

    mock_client = MagicMock()
    mock_client.server_info.return_value = fake_server_info
    mock_client.list_tools.return_value = fake_tools

    entry = {"url": "http://host/mcp", "auth_type": "none", "auth_value": "", "name": ""}

    with patch("mcp.manager.GenericMCPClient", return_value=mock_client), \
         patch("mcp.manager._save_connections"), \
         patch("mcp.manager._load_connections", return_value=[]):
        result = add_or_update(entry)

    assert result["ok"] is True
    assert result["name"] == "CRM"
    assert result["tool_count"] == 1
    _unregister(result["id"])


def test_add_or_update_stdio_routes_to_stdio_client():
    import shared
    from mcp.manager import add_or_update, _unregister

    fake_tools = [{"name": "echo", "description": "Echo", "inputSchema": {"type": "object"}}]
    fake_server_info = {"name": "fake", "version": "0.1"}

    mock_client = MagicMock()
    mock_client.server_info.return_value = fake_server_info
    mock_client.list_tools.return_value = fake_tools
    mock_client.close = MagicMock()

    entry = {
        "transport": "stdio",
        "command": "npx",
        "args": ["@playwright/mcp@latest"],
        "env": {},
        "name": "",
    }

    with patch("mcp.manager.StdioMCPClient", return_value=mock_client), \
         patch("mcp.manager._save_connections"), \
         patch("mcp.manager._load_connections", return_value=[]):
        result = add_or_update(entry)

    assert result["ok"] is True
    assert result["name"] == "fake"
    assert result["tool_count"] == 1
    _unregister(result["id"])


def test_add_or_update_stdio_requires_command():
    from mcp.manager import add_or_update

    entry = {"transport": "stdio", "command": "", "args": [], "env": {}, "name": ""}
    result = add_or_update(entry)
    assert result["ok"] is False
    assert "command" in result["error"].lower()


def test_load_all_from_cache_migrates_missing_transport():
    """A connection record without a `transport` field is treated as 'http'."""
    import shared
    from mcp.manager import load_all_from_cache, _unregister

    conn = _sample_conn()
    assert "transport" not in conn  # the fixture pre-dates the field
    _unregister(conn["id"])

    with patch("mcp.manager._load_connections", return_value=[conn]):
        load_all_from_cache()

    assert "mcp-crm" in shared.SKILL_TOOLS_MAP
    _unregister(conn["id"])


def test_add_or_update_stdio_uses_command_name_when_no_server_name():
    """If server_info has no name, fall back to the user-supplied name."""
    import shared
    from mcp.manager import add_or_update, _unregister

    mock_client = MagicMock()
    mock_client.server_info.return_value = {"name": "", "version": ""}
    mock_client.list_tools.return_value = [{"name": "x", "description": "", "inputSchema": {}}]

    entry = {
        "transport": "stdio",
        "command": "npx",
        "args": ["pkg"],
        "env": {},
        "name": "playwright",   # supplied from parse_mcp_json (the mcpServers key)
    }

    with patch("mcp.manager.StdioMCPClient", return_value=mock_client), \
         patch("mcp.manager._save_connections"), \
         patch("mcp.manager._load_connections", return_value=[]):
        result = add_or_update(entry)

    assert result["ok"] is True
    assert result["name"] == "playwright"
    _unregister(result["id"])


def test_handler_surfaces_command_not_found():
    """Tool handler must return a structured error dict — never raise — when
    the underlying stdio command isn't on PATH."""
    import shared
    from mcp.manager import _register, _unregister

    conn = {
        "id": "mcp-missing",
        "name": "missing",
        "transport": "stdio",
        "command": "this-does-not-exist-12345",
        "args": [],
        "env": {},
        "enabled": True,
        "cached_tools": [
            {"name": "do_thing", "description": "", "input_schema": {"type": "object", "properties": {}}}
        ],
    }
    _unregister(conn["id"])
    try:
        _register(conn)
        handler = shared.TOOL_DISPATCH["mcp-missing__do_thing"]
        # Must NOT raise — must return an error dict.
        result = handler()
        assert isinstance(result, dict)
        assert "error" in result
        assert "command not found" in result["error"].lower() or "not found" in result["error"].lower()
        assert result.get("transport") == "stdio"
    finally:
        _unregister(conn["id"])


def test_load_connections_skips_malformed():
    """Legacy/corrupt config entries that aren't dicts must be skipped, not crash startup."""
    import shared
    from mcp.manager import load_all_from_cache, _unregister

    good = _sample_conn(id="mcp-good", name="Good")
    _unregister(good["id"])

    legacy_cfg = {"mcp_connections": [good, "garbage-string-entry", None, 42]}

    with patch("mcp.manager._load_config", return_value=legacy_cfg):
        # Must not raise.
        load_all_from_cache()

    assert "mcp-good" in shared.SKILL_TOOLS_MAP
    assert "mcp-good__crm_get_contact" in shared.TOOL_DISPATCH
    _unregister(good["id"])


def test_add_or_update_serializes_concurrent_calls():
    """Two threads calling add_or_update concurrently must not lose either record.

    Without the module-level lock, the classic lost-update race fires:
      T1 loads [] → T2 loads [] → T1 saves [A] → T2 saves [B]   (A is lost)
    We force the interleaving deterministically with a Barrier that holds both
    threads inside _load_connections() at the same instant — exactly the
    window the lock must cover. With the lock present, the second thread
    blocks at the lock and reaches _load_connections only after the first
    thread has saved, so the Barrier is irrelevant (it has timeout=0.5)."""
    import shared
    from mcp.manager import add_or_update, _unregister

    fake_tools = [{"name": "echo", "description": "Echo", "inputSchema": {"type": "object"}}]

    storage = {"connections": []}
    storage_lock = threading.Lock()
    # Force both threads to (a) load, then (b) save together. Without the
    # mutation lock, both threads load [], then both save [their_conn] — the
    # last save wins, so one record is lost. With the lock, the second thread
    # blocks at the manager lock, never reaches load_barrier, so it times out
    # (BrokenBarrierError) and the test exits cleanly — assertion still passes.
    load_barrier = threading.Barrier(2, timeout=0.5)
    save_barrier = threading.Barrier(2, timeout=0.5)

    def fake_load_connections():
        with storage_lock:
            snap = [dict(c) for c in storage["connections"]]
        # Block here AFTER loading so both threads load the SAME state.
        try:
            load_barrier.wait()
        except threading.BrokenBarrierError:
            pass
        return snap

    def fake_save_connections(conns):
        # Block here BEFORE saving so both threads have computed their
        # update from the (identical) load snapshot before either commits.
        try:
            save_barrier.wait()
        except threading.BrokenBarrierError:
            pass
        with storage_lock:
            storage["connections"] = [dict(c) for c in conns]

    def client_factory(cfg):
        url = cfg.get("url", "")
        server_name = url.split("//")[-1].split("/")[0]
        mc = MagicMock()
        mc.server_info.return_value = {"name": server_name, "version": "1.0"}
        mc.list_tools.return_value = fake_tools
        mc.close = MagicMock()
        return mc

    errors: list[BaseException] = []
    results: list[dict] = []
    results_lock = threading.Lock()

    def worker(server_name):
        try:
            r = add_or_update({"url": f"http://{server_name}/mcp", "auth_type": "none", "auth_value": "", "name": server_name})
            with results_lock:
                results.append(r)
        except BaseException as e:
            with results_lock:
                errors.append(e)

    # Patch ONCE at module level — patch contexts aren't thread-safe.
    with patch("mcp.manager.GenericMCPClient", side_effect=client_factory), \
         patch("mcp.manager._save_connections", side_effect=fake_save_connections), \
         patch("mcp.manager._load_connections", side_effect=fake_load_connections):
        t1 = threading.Thread(target=worker, args=("alpha",))
        t2 = threading.Thread(target=worker, args=("beta",))
        t1.start(); t2.start()
        t1.join(); t2.join()

    assert not errors, f"Concurrent add_or_update raised: {errors}"
    assert len(results) == 2
    assert all(r.get("ok") for r in results)
    final = storage["connections"]
    ids = sorted(c.get("id") for c in final)
    # Both records must be present — neither lost to a race.
    assert ids == ["mcp-alpha", "mcp-beta"], f"Lost-update race — final connections: {final}"
    _unregister("mcp-alpha")
    _unregister("mcp-beta")
