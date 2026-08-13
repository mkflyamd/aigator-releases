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
                "input_schema": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
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
        {
            "name": "crm_get_contact",
            "description": "Get contact",
            "inputSchema": {"type": "object", "properties": {}},
        }
    ]
    fake_server_info = {"name": "CRM", "version": "1.0"}

    mock_client = MagicMock()
    mock_client.server_info.return_value = fake_server_info
    mock_client.list_tools.return_value = fake_tools
    mock_client.call_probe.return_value = (
        False,
        "",
    )  # (is_error, text) — probe succeeds

    entry = {
        "url": "http://host/mcp",
        "auth_type": "none",
        "auth_value": "",
        "name": "",
    }

    with (
        patch("mcp.manager.GenericMCPClient", return_value=mock_client),
        patch("mcp.manager._save_connections"),
        patch("mcp.manager._load_connections", return_value=[]),
    ):
        result = add_or_update(entry)

    assert result["ok"] is True
    assert result["name"] == "CRM"
    assert result["tool_count"] == 1
    _unregister(result["id"])


def test_add_or_update_stdio_routes_to_stdio_client():
    import shared
    from mcp.manager import add_or_update, _unregister

    fake_tools = [
        {"name": "echo", "description": "Echo", "inputSchema": {"type": "object"}}
    ]
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

    with (
        patch("mcp.manager.StdioMCPClient", return_value=mock_client),
        patch("mcp.manager._save_connections"),
        patch("mcp.manager._load_connections", return_value=[]),
    ):
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
    mock_client.list_tools.return_value = [
        {"name": "x", "description": "", "inputSchema": {}}
    ]

    entry = {
        "transport": "stdio",
        "command": "npx",
        "args": ["pkg"],
        "env": {},
        "name": "playwright",  # supplied from parse_mcp_json (the mcpServers key)
    }

    with (
        patch("mcp.manager.StdioMCPClient", return_value=mock_client),
        patch("mcp.manager._save_connections"),
        patch("mcp.manager._load_connections", return_value=[]),
    ):
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
            {
                "name": "do_thing",
                "description": "",
                "input_schema": {"type": "object", "properties": {}},
            }
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
        assert (
            "command not found" in result["error"].lower()
            or "not found" in result["error"].lower()
        )
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

    fake_tools = [
        {"name": "echo", "description": "Echo", "inputSchema": {"type": "object"}}
    ]

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
        mc.call_probe.return_value = (False, "")  # (is_error, text) — probe succeeds
        mc.close = MagicMock()
        return mc

    errors: list[BaseException] = []
    results: list[dict] = []
    results_lock = threading.Lock()

    def worker(server_name):
        try:
            r = add_or_update(
                {
                    "url": f"http://{server_name}/mcp",
                    "auth_type": "none",
                    "auth_value": "",
                    "name": server_name,
                }
            )
            with results_lock:
                results.append(r)
        except BaseException as e:
            with results_lock:
                errors.append(e)

    # Patch ONCE at module level — patch contexts aren't thread-safe.
    with (
        patch("mcp.manager.GenericMCPClient", side_effect=client_factory),
        patch("mcp.manager._save_connections", side_effect=fake_save_connections),
        patch("mcp.manager._load_connections", side_effect=fake_load_connections),
    ):
        t1 = threading.Thread(target=worker, args=("alpha",))
        t2 = threading.Thread(target=worker, args=("beta",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    assert not errors, f"Concurrent add_or_update raised: {errors}"
    assert len(results) == 2
    assert all(r.get("ok") for r in results)
    final = storage["connections"]
    ids = sorted(c.get("id") for c in final)
    # Both records must be present — neither lost to a race.
    assert ids == ["mcp-alpha", "mcp-beta"], (
        f"Lost-update race — final connections: {final}"
    )
    _unregister("mcp-alpha")
    _unregister("mcp-beta")


# ── Plugin-owned MCP connections (Phase E, 2026-08-07 milestone, decision #5,
# Increment 3) — register_plugin_mcp_server / remove_plugin_mcp_servers. ─────


def test_register_plugin_mcp_server_self_contained_enables_and_tags_owner():
    """A self-contained stdio server (no missing secrets) goes through
    add_or_update's real connect/probe path and ends up enabled, tagged with
    plugin_id for teardown/UI ownership."""
    from mcp.manager import register_plugin_mcp_server, _unregister

    mock_client = MagicMock()
    mock_client.server_info.return_value = {"name": "filesystem", "version": "1.0"}
    mock_client.list_tools.return_value = [
        {
            "name": "list_dir",
            "description": "List a dir",
            "inputSchema": {"type": "object", "properties": {}},
        }
    ]

    provisional = {
        "transport": "stdio",
        "command": "npx",
        "args": ["pkg"],
        "env": {},
        "name": "filesystem",
    }

    with (
        patch("mcp.manager.StdioMCPClient", return_value=mock_client),
        patch("mcp.manager._save_connections") as mock_save,
        patch("mcp.manager._load_connections", return_value=[]),
    ):
        result = register_plugin_mcp_server(
            "fs-plugin", "filesystem", provisional, missing_secrets=[]
        )

    assert result == {
        "ok": True,
        "id": "plugin:fs-plugin:filesystem",
        "enabled": True,
        "tool_count": 1,
    }
    # Second save call re-tags plugin_id on top of add_or_update's own record.
    saved_conns = mock_save.call_args_list[-1].args[0]
    conn = next(c for c in saved_conns if c["id"] == "plugin:fs-plugin:filesystem")
    assert conn["plugin_id"] == "fs-plugin"
    assert conn["enabled"] is True
    _unregister("plugin:fs-plugin:filesystem")


def test_register_plugin_mcp_server_missing_secret_never_spawns():
    """A declared server with an unresolved {PLACEHOLDER} secret must be
    persisted disabled WITHOUT ever attempting to connect/spawn."""
    from mcp.manager import register_plugin_mcp_server

    provisional = {
        "transport": "stdio",
        "command": "npx",
        "args": ["pkg"],
        "env": {"DATADOG_API_KEY": "{DATADOG_API_KEY}"},
        "name": "datadog",
    }

    with (
        patch("mcp.manager.StdioMCPClient") as mock_cls,
        patch("mcp.manager._save_connections") as mock_save,
        patch("mcp.manager._load_connections", return_value=[]),
    ):
        result = register_plugin_mcp_server(
            "dd-plugin", "datadog", provisional, missing_secrets=["DATADOG_API_KEY"]
        )

    mock_cls.assert_not_called()
    assert result["ok"] is True
    assert result["enabled"] is False
    assert result["missing_secrets"] == ["DATADOG_API_KEY"]
    saved_conns = mock_save.call_args_list[-1].args[0]
    conn = next(c for c in saved_conns if c["id"] == "plugin:dd-plugin:datadog")
    assert conn["enabled"] is False
    assert conn["missing_secrets"] == ["DATADOG_API_KEY"]
    assert conn["cached_tools"] == []


def test_register_plugin_mcp_server_connect_failure_persists_disabled_not_raise():
    """If the self-contained server's process fails to spawn/connect (e.g.
    command not found), the plugin install must not blow up — a disabled
    placeholder connection recording the error is persisted instead."""
    from mcp.manager import register_plugin_mcp_server

    provisional = {
        "transport": "stdio",
        "command": "this-does-not-exist-xyz",
        "args": [],
        "env": {},
        "name": "broken",
    }

    with (
        patch("mcp.manager._save_connections") as mock_save,
        patch("mcp.manager._load_connections", return_value=[]),
    ):
        result = register_plugin_mcp_server(
            "broken-plugin", "broken", provisional, missing_secrets=[]
        )

    assert result["ok"] is False
    assert result["id"] == "plugin:broken-plugin:broken"
    assert "error" in result
    saved_conns = mock_save.call_args_list[-1].args[0]
    conn = next(c for c in saved_conns if c["id"] == "plugin:broken-plugin:broken")
    assert conn["enabled"] is False
    assert "connect_error" in conn


def test_remove_plugin_mcp_servers_removes_all_owned_connections():
    """remove_plugin_mcp_servers must delegate to the same remove() a manual
    single-connection delete uses, for every connection owned by plugin_id —
    matched by the plugin_id field (id-prefix is a fallback, not required
    here since register_plugin_mcp_server always sets both)."""
    from mcp.manager import remove_plugin_mcp_servers, _unregister

    owned_a = {
        "id": "plugin:fs-plugin:filesystem",
        "name": "filesystem",
        "transport": "stdio",
        "command": "npx",
        "args": [],
        "env": {},
        "enabled": True,
        "plugin_id": "fs-plugin",
        "cached_tools": [
            {
                "name": "list_dir",
                "description": "",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    }
    owned_b = {
        "id": "plugin:fs-plugin:search",
        "name": "search",
        "transport": "http",
        "url": "http://x/mcp",
        "auth_type": "none",
        "auth_value": "",
        "enabled": True,
        "plugin_id": "fs-plugin",
        "cached_tools": [],
    }
    unrelated = {
        "id": "mcp-user-added",
        "name": "other",
        "transport": "http",
        "url": "http://y/mcp",
        "auth_type": "none",
        "auth_value": "",
        "enabled": True,
        "cached_tools": [],
    }
    # remove() is called once per owned connection and persists after each
    # call — a static return_value would make the second call "see" the
    # first connection as still present (never-mutated snapshot), so use a
    # real backing store that fake_load/fake_save read/write against, same
    # pattern as test_add_or_update_serializes_concurrent_calls above.
    storage = {"connections": [owned_a, owned_b, unrelated]}

    with (
        patch(
            "mcp.manager._load_connections",
            side_effect=lambda: list(storage["connections"]),
        ),
        patch(
            "mcp.manager._save_connections",
            side_effect=lambda conns: storage.__setitem__("connections", list(conns)),
        ),
        patch("mcp.manager.release_from_pool") as mock_release,
    ):
        removed = remove_plugin_mcp_servers("fs-plugin")

    assert sorted(removed) == ["plugin:fs-plugin:filesystem", "plugin:fs-plugin:search"]
    # Both owned connections gone, unrelated user-added one untouched.
    assert [c["id"] for c in storage["connections"]] == ["mcp-user-added"]
    # release_from_pool called once, for the stdio-owned connection only.
    mock_release.assert_called_once()
    _unregister("mcp-user-added")


def test_plugin_connection_id_escapes_colon_to_avoid_collision():
    """Fix #7 (2026-08-07 milestone adversarial review): a colon embedded in
    plugin_id or server_name must not let two different (plugin_id,
    server_name) pairs collide under naive string concatenation."""
    from mcp.manager import _plugin_connection_id

    id_a = _plugin_connection_id("foo", "bar:baz")
    id_b = _plugin_connection_id("foo:bar", "baz")
    assert id_a != id_b


def test_register_plugin_mcp_server_http_connect_failure_keeps_full_field_set():
    """Fix #8: the connect-failure disabled-connection record for an http
    transport must include auth_type/auth_value/extra_headers — same as the
    missing-secrets branch and add_or_update itself always set. These had
    silently drifted out of the connect_error branch."""
    from mcp.manager import register_plugin_mcp_server

    provisional = {
        "transport": "http",
        "url": "http://bad-host/mcp",
        "auth_type": "bearer",
        "auth_value": "secret-token",
        "headers": {"X-Custom": "value"},
        "name": "broken-http",
    }

    with (
        patch(
            "mcp.manager.GenericMCPClient",
            side_effect=RuntimeError("Connection refused"),
        ),
        patch("mcp.manager._save_connections") as mock_save,
        patch("mcp.manager._load_connections", return_value=[]),
    ):
        result = register_plugin_mcp_server(
            "http-plugin", "broken-http", provisional, missing_secrets=[]
        )

    assert result["ok"] is False
    saved_conns = mock_save.call_args_list[-1].args[0]
    conn = next(c for c in saved_conns if c["id"] == "plugin:http-plugin:broken-http")
    assert conn["auth_type"] == "bearer"
    assert conn["auth_value"] == "secret-token"
    assert conn["extra_headers"] == {"X-Custom": "value"}


def test_register_plugin_mcp_server_timeout_persists_disabled_connect_error(
    monkeypatch,
):
    """Fix #4: a slow/hanging add_or_update call must not block the install
    request indefinitely — bounded by an overall timeout, then treated
    exactly like any other connect failure (disabled connection persisted
    with connect_error set)."""
    import time
    from mcp.manager import register_plugin_mcp_server

    monkeypatch.setattr("mcp.manager._PLUGIN_MCP_CONNECT_TIMEOUT_S", 0.2)

    def _hang(entry):
        time.sleep(2)
        return {"ok": True, "id": "should-not-be-used", "tool_count": 1}

    provisional = {
        "transport": "stdio",
        "command": "npx",
        "args": ["pkg"],
        "env": {},
        "name": "slow",
    }

    with (
        patch("mcp.manager.add_or_update", side_effect=_hang),
        patch("mcp.manager._save_connections") as mock_save,
        patch("mcp.manager._load_connections", return_value=[]),
    ):
        start = time.monotonic()
        result = register_plugin_mcp_server(
            "slow-plugin", "slow", provisional, missing_secrets=[]
        )
        elapsed = time.monotonic() - start

    assert elapsed < 1.5, "must not have waited for the full hang"
    assert result["ok"] is False
    assert result["id"] == "plugin:slow-plugin:slow"
    assert "timed out" in result["error"].lower()

    saved_conns = mock_save.call_args_list[-1].args[0]
    conn = next(c for c in saved_conns if c["id"] == "plugin:slow-plugin:slow")
    assert conn["enabled"] is False
    assert "timed out" in conn["connect_error"].lower()


def test_register_plugin_mcp_server_add_or_update_race_removed_returns_failure():
    """Fix #9: if the connection is removed concurrently between
    add_or_update's own save and register_plugin_mcp_server's follow-up
    plugin_id-stamp save, the stamp step's lookup finds nothing — this must
    report a real failure, not a phantom ok:True for a connection that no
    longer exists."""
    from mcp.manager import register_plugin_mcp_server

    provisional = {
        "transport": "stdio",
        "command": "npx",
        "args": ["pkg"],
        "env": {},
        "name": "svc",
    }

    with (
        patch(
            "mcp.manager.add_or_update",
            return_value={"ok": True, "id": "plugin:race-plugin:svc", "tool_count": 1},
        ),
        patch("mcp.manager._load_connections", return_value=[]),
        patch("mcp.manager._save_connections") as mock_save,
    ):
        result = register_plugin_mcp_server(
            "race-plugin", "svc", provisional, missing_secrets=[]
        )

    assert result == {
        "ok": False,
        "id": "plugin:race-plugin:svc",
        "error": "connection was removed concurrently during registration",
    }
    mock_save.assert_not_called()


def test_remove_plugin_mcp_servers_continues_after_one_failure_and_reports_it(caplog):
    """Fix #5: a failure removing connection 2-of-3 must not abort removal of
    the rest — the other owned connections still get torn down, and the
    failure is attributable to a specific connection id, not folded into a
    generic message."""
    import logging
    from mcp.manager import remove_plugin_mcp_servers

    owned = [
        {"id": "plugin:multi-plugin:one", "plugin_id": "multi-plugin"},
        {"id": "plugin:multi-plugin:two", "plugin_id": "multi-plugin"},
        {"id": "plugin:multi-plugin:three", "plugin_id": "multi-plugin"},
    ]

    def fake_remove(conn_id):
        if conn_id == "plugin:multi-plugin:two":
            raise RuntimeError("boom")
        return {"ok": True}

    with (
        patch("mcp.manager._load_connections", return_value=owned),
        patch("mcp.manager.remove", side_effect=fake_remove),
        caplog.at_level(logging.WARNING, logger="mcp.manager"),
    ):
        removed = remove_plugin_mcp_servers("multi-plugin")

    assert removed == ["plugin:multi-plugin:one", "plugin:multi-plugin:three"]
    assert any(
        "plugin:multi-plugin:two" in rec.message and "boom" in rec.message
        for rec in caplog.records
    )


def test_remove_plugin_mcp_servers_matches_by_id_prefix_fallback():
    """Even without an explicit plugin_id field (e.g. a hand-crafted or
    legacy record), the id-prefix convention alone is enough to find and
    remove a plugin's connections."""
    from mcp.manager import remove_plugin_mcp_servers

    legacy_owned = {
        "id": "plugin:old-plugin:server",
        "name": "server",
        "transport": "http",
        "url": "http://z/mcp",
        "auth_type": "none",
        "auth_value": "",
        "enabled": True,
        "cached_tools": [],
    }
    with (
        patch("mcp.manager._load_connections", return_value=[legacy_owned]),
        patch("mcp.manager._save_connections") as mock_save,
    ):
        removed = remove_plugin_mcp_servers("old-plugin")

    assert removed == ["plugin:old-plugin:server"]
    assert mock_save.call_args_list[-1].args[0] == []


# ── Secret completion for a pending connection (Increment 4b, 2026-08-07
# milestone) — complete_pending_secrets. ─────────────────────────────────


def test_complete_pending_secrets_stdio_resolves_placeholder_and_enables():
    """{PLACEHOLDER} syntax in env AND a CLI arg both get resolved (mirrors
    _missing_secrets_for_server's own args-scanning fix), the connection
    flips enabled, plugin_id survives, and missing_secrets is cleared."""
    from mcp.manager import complete_pending_secrets, _unregister

    pending = {
        "id": "plugin:dd-plugin:datadog",
        "name": "datadog",
        "transport": "stdio",
        "enabled": False,
        "cached_tools": [],
        "plugin_id": "dd-plugin",
        "missing_secrets": ["DATADOG_API_KEY"],
        "command": "npx",
        "args": ["datadog-mcp", "--key", "{DATADOG_API_KEY}"],
        "env": {"DATADOG_API_KEY": "{DATADOG_API_KEY}"},
    }
    connections = [pending]

    mock_client = MagicMock()
    mock_client.server_info.return_value = {"name": "datadog", "version": "1.0"}
    mock_client.list_tools.return_value = [
        {
            "name": "get_metrics",
            "description": "Get metrics",
            "inputSchema": {"type": "object", "properties": {}},
        }
    ]

    with (
        patch("mcp.manager.StdioMCPClient", return_value=mock_client),
        patch("mcp.manager._save_connections") as mock_save,
        patch("mcp.manager._load_connections", return_value=connections),
    ):
        result = complete_pending_secrets(
            "plugin:dd-plugin:datadog", {"DATADOG_API_KEY": "secret123"}
        )

    assert result["ok"] is True
    assert result["tool_count"] == 1
    saved = mock_save.call_args_list[-1].args[0]
    conn = next(c for c in saved if c["id"] == "plugin:dd-plugin:datadog")
    assert conn["enabled"] is True
    assert conn["plugin_id"] == "dd-plugin"
    assert "missing_secrets" not in conn
    assert conn["env"]["DATADOG_API_KEY"] == "secret123"
    assert conn["args"][-1] == "secret123"
    _unregister("plugin:dd-plugin:datadog")


def test_complete_pending_secrets_http_resolves_empty_string_convention():
    """The "declared as an empty string" convention (no {VAR} substring to
    substitute against) is resolved by direct key match against `values`."""
    from mcp.manager import complete_pending_secrets, _unregister

    pending = {
        "id": "plugin:pg-plugin:postgres",
        "name": "postgres",
        "transport": "http",
        "enabled": False,
        "cached_tools": [],
        "plugin_id": "pg-plugin",
        "missing_secrets": ["X-Api-Key"],
        "url": "https://example.com/mcp",
        "auth_type": "none",
        "auth_value": "",
        "extra_headers": {"X-Api-Key": ""},
    }
    connections = [pending]

    mock_client = MagicMock()
    mock_client.server_info.return_value = {"name": "postgres", "version": "2.0"}
    mock_client.list_tools.return_value = [
        {
            "name": "query",
            "description": "Run a query",
            "inputSchema": {"type": "object", "properties": {}},
        }
    ]
    # Sidesteps a pre-existing, unrelated bug (see test_add_or_update_connects_
    # and_caches / test_add_or_update_serializes_concurrent_calls, both already
    # failing on main): _probe_tools_for_auth unpacks client.call_probe(...)
    # as a 2-tuple, which a bare MagicMock doesn't support. Configuring it
    # explicitly keeps this new test from tripping over that unrelated bug.
    mock_client.call_probe.return_value = (False, "")

    with (
        patch("mcp.manager.GenericMCPClient", return_value=mock_client),
        patch("mcp.manager._save_connections") as mock_save,
        patch("mcp.manager._load_connections", return_value=connections),
    ):
        result = complete_pending_secrets(
            "plugin:pg-plugin:postgres", {"X-Api-Key": "sekrit"}
        )

    assert result["ok"] is True
    saved = mock_save.call_args_list[-1].args[0]
    conn = next(c for c in saved if c["id"] == "plugin:pg-plugin:postgres")
    assert conn["enabled"] is True
    assert conn["extra_headers"]["X-Api-Key"] == "sekrit"
    assert conn["plugin_id"] == "pg-plugin"
    assert "missing_secrets" not in conn
    _unregister("plugin:pg-plugin:postgres")


def test_complete_pending_secrets_connect_failure_preserves_plugin_id():
    """A bad credential / connect failure must leave the connection pending
    with an updated connect_error — plugin_id (ownership metadata) must
    survive so the plugin can still be uninstalled or retried later."""
    from mcp.manager import complete_pending_secrets

    pending = {
        "id": "plugin:broken-plugin:broken",
        "name": "broken",
        "transport": "stdio",
        "enabled": False,
        "cached_tools": [],
        "plugin_id": "broken-plugin",
        "missing_secrets": ["API_KEY"],
        "command": "this-does-not-exist-xyz",
        "args": [],
        "env": {"API_KEY": "{API_KEY}"},
    }
    connections = [pending]

    with (
        patch("mcp.manager._save_connections") as mock_save,
        patch("mcp.manager._load_connections", return_value=connections),
    ):
        result = complete_pending_secrets(
            "plugin:broken-plugin:broken", {"API_KEY": "secret"}
        )

    assert result["ok"] is False
    assert "error" in result
    saved = mock_save.call_args_list[-1].args[0]
    conn = next(c for c in saved if c["id"] == "plugin:broken-plugin:broken")
    assert conn["enabled"] is False
    assert conn["plugin_id"] == "broken-plugin"
    assert "connect_error" in conn


def test_complete_pending_secrets_connection_not_found():
    from mcp.manager import complete_pending_secrets

    with patch("mcp.manager._load_connections", return_value=[]):
        result = complete_pending_secrets("plugin:ghost:server", {"X": "y"})

    assert result == {"ok": False, "error": "Connection not found"}


def test_complete_pending_secrets_failure_masks_secret_in_connect_error():
    """Fix #1 (HIGH, credential leak, 2026-08-07 milestone adversarial
    review): a connect_error that echoes the caller-supplied secret value
    verbatim (e.g. GenericMCPClient's "Connection refused — is the server
    running at {url}?" messages, where the url embeds a resolved
    ?api_key={KEY} query param) must never be persisted or returned with
    the raw secret still readable."""
    from mcp.manager import complete_pending_secrets

    secret = "sk-super-secret-value-12345"
    pending = {
        "id": "plugin:leaky-plugin:leaky",
        "name": "leaky",
        "transport": "http",
        "enabled": False,
        "cached_tools": [],
        "plugin_id": "leaky-plugin",
        "missing_secrets": ["API_KEY"],
        "url": "https://example.com/mcp?api_key={API_KEY}",
        "auth_type": "none",
        "auth_value": "",
        "extra_headers": {},
    }
    connections = [pending]
    fake_error = f"Connection refused — is the server running at https://example.com/mcp?api_key={secret}?"

    with (
        patch(
            "mcp.manager.add_or_update", return_value={"ok": False, "error": fake_error}
        ),
        patch("mcp.manager._save_connections") as mock_save,
        patch("mcp.manager._load_connections", return_value=connections),
    ):
        result = complete_pending_secrets(
            "plugin:leaky-plugin:leaky", {"API_KEY": secret}
        )

    assert result["ok"] is False
    assert secret not in result["error"], (
        "raw secret must not appear in the returned error"
    )
    saved = mock_save.call_args_list[-1].args[0]
    conn = next(c for c in saved if c["id"] == "plugin:leaky-plugin:leaky")
    assert secret not in conn["connect_error"], (
        "raw secret must not appear in the persisted connect_error"
    )


def test_complete_pending_secrets_rejects_empty_values_without_touching_connection():
    """Fix #2 (2026-08-07 milestone adversarial review): submitting no
    values at all for a connection with missing_secrets must fail cleanly
    — without calling add_or_update and without mutating the stored
    connection record (still pending, still showing the same
    missing_secrets)."""
    from mcp.manager import complete_pending_secrets

    pending = {
        "id": "plugin:dd-plugin:datadog",
        "name": "datadog",
        "transport": "stdio",
        "enabled": False,
        "cached_tools": [],
        "plugin_id": "dd-plugin",
        "missing_secrets": ["DATADOG_API_KEY"],
        "command": "npx",
        "args": ["datadog-mcp", "--key", "{DATADOG_API_KEY}"],
        "env": {"DATADOG_API_KEY": "{DATADOG_API_KEY}"},
    }
    connections = [pending]

    with (
        patch("mcp.manager.add_or_update") as mock_add_or_update,
        patch("mcp.manager._save_connections") as mock_save,
        patch("mcp.manager._load_connections", return_value=connections),
    ):
        result = complete_pending_secrets("plugin:dd-plugin:datadog", {})

    assert result["ok"] is False
    assert "DATADOG_API_KEY" in result["error"]
    mock_add_or_update.assert_not_called()
    mock_save.assert_not_called()
    # Untouched — same object, still pending with the same missing_secrets.
    assert pending["enabled"] is False
    assert pending["missing_secrets"] == ["DATADOG_API_KEY"]
    assert "connect_error" not in pending


def test_complete_pending_secrets_rejects_one_blank_of_several_required():
    """Fix #2: even if most required secrets are supplied, a single blank
    or missing one among several must still block the call — not silently
    proceed with a half-resolved credential set."""
    from mcp.manager import complete_pending_secrets

    pending = {
        "id": "plugin:multi-plugin:multi",
        "name": "multi",
        "transport": "http",
        "enabled": False,
        "cached_tools": [],
        "plugin_id": "multi-plugin",
        "missing_secrets": ["API_KEY", "API_SECRET", "TENANT_ID"],
        "url": "https://example.com/mcp",
        "auth_type": "none",
        "auth_value": "",
        "extra_headers": {"X-Api-Key": "{API_KEY}", "X-Api-Secret": "{API_SECRET}"},
    }
    connections = [pending]

    with (
        patch("mcp.manager.add_or_update") as mock_add_or_update,
        patch("mcp.manager._save_connections") as mock_save,
        patch("mcp.manager._load_connections", return_value=connections),
    ):
        # TENANT_ID omitted entirely; API_SECRET submitted blank.
        result = complete_pending_secrets(
            "plugin:multi-plugin:multi", {"API_KEY": "abc123", "API_SECRET": "   "}
        )

    assert result["ok"] is False
    assert "API_SECRET" in result["error"]
    assert "TENANT_ID" in result["error"]
    mock_add_or_update.assert_not_called()
    mock_save.assert_not_called()
    assert pending["enabled"] is False
    assert pending["missing_secrets"] == ["API_KEY", "API_SECRET", "TENANT_ID"]


def test_list_with_status_surfaces_plugin_ownership_and_pending_fields():
    """list_with_status() must expose plugin_id/missing_secrets/connect_error
    when present (Increment 3's own open TODO: 'list_with_status() doesn't
    yet expose it') so the Connections settings UI can render pending rows,
    but must not add these keys for a normal manually-added connection."""
    from mcp.manager import list_with_status

    pending = {
        "id": "plugin:dd-plugin:datadog",
        "name": "datadog",
        "transport": "stdio",
        "enabled": False,
        "cached_tools": [],
        "plugin_id": "dd-plugin",
        "missing_secrets": ["DATADOG_API_KEY"],
        "command": "npx",
        "args": [],
        "env": {},
    }
    manual = {
        "id": "mcp-crm",
        "name": "CRM",
        "transport": "http",
        "enabled": True,
        "url": "http://host/mcp",
        "auth_type": "none",
        "auth_value": "",
        "cached_tools": [],
    }

    with patch("mcp.manager._load_connections", return_value=[pending, manual]):
        rows = list_with_status()

    pending_row = next(r for r in rows if r["id"] == "plugin:dd-plugin:datadog")
    manual_row = next(r for r in rows if r["id"] == "mcp-crm")
    assert pending_row["plugin_id"] == "dd-plugin"
    assert pending_row["missing_secrets"] == ["DATADOG_API_KEY"]
    assert "connect_error" not in pending_row
    assert "plugin_id" not in manual_row
    assert "missing_secrets" not in manual_row


# ---------------------------------------------------------------------------
# _substitute_placeholder / complete_pending_secrets — bash-parameter-
# expansion syntax (2026-08-07 milestone gap #2 fix). A bare
# `.replace("{VAR}", val)` either misses "${VAR:-default}" entirely (no
# "{VAR}" substring exists inside it) or, for plain "${VAR}" with no
# default, leaves a stray leading "$" behind (since "{VAR}" is a substring
# of "${VAR}"). The full "${...}" span must be replaced instead.
# ---------------------------------------------------------------------------


def test_substitute_placeholder_bash_style_with_default_replaces_full_span():
    from mcp.manager import _substitute_placeholder

    out = _substitute_placeholder(
        "https://${DD_MCP_DOMAIN:-not-setup}/v1/mcp",
        {"DD_MCP_DOMAIN": "api.datadoghq.com"},
    )
    assert out == "https://api.datadoghq.com/v1/mcp"


def test_substitute_placeholder_bash_style_empty_default_replaces_full_span():
    from mcp.manager import _substitute_placeholder

    out = _substitute_placeholder("${DD_API_KEY:-}", {"DD_API_KEY": "secret123"})
    assert out == "secret123"


def test_substitute_placeholder_bash_style_no_default_does_not_leave_stray_dollar():
    """Plain "${VAR}" (no default) must resolve to the value with NO leftover
    "$" prefix — a bare-brace-only replace would produce "$" + value here."""
    from mcp.manager import _substitute_placeholder

    out = _substitute_placeholder("${API_KEY}", {"API_KEY": "secret123"})
    assert out == "secret123"


def test_substitute_placeholder_bare_brace_still_works():
    from mcp.manager import _substitute_placeholder

    out = _substitute_placeholder("{API_KEY}", {"API_KEY": "secret123"})
    assert out == "secret123"


def test_substitute_placeholder_unresolved_var_left_untouched():
    from mcp.manager import _substitute_placeholder

    out = _substitute_placeholder("${OTHER_VAR:-fallback}", {"API_KEY": "secret123"})
    assert out == "${OTHER_VAR:-fallback}"


# ---------------------------------------------------------------------------
# Fix 3 (pre-existing bug, adversarial review): sequential multi-key
# substitution could corrupt an already-substituted secret value if that
# value's own text happened to look like another placeholder. Fixed by a
# single combined-regex re.sub() pass over the ORIGINAL string, mirroring
# marketplace.commands.expand_command's $ARGUMENTS/positional-regex fix.
# ---------------------------------------------------------------------------


def test_substitute_placeholder_does_not_corrupt_value_shaped_like_another_placeholder():
    from mcp.manager import _substitute_placeholder

    values = {"KEY1": "abc{KEY2}xyz", "KEY2": "realsecretvalue"}
    out = _substitute_placeholder("${KEY1:-}", values)
    assert out == "abc{KEY2}xyz"


def test_substitute_placeholder_corruption_fix_is_order_independent():
    """Same repro as above, but with the values dict built in the opposite
    key order — the fix must not depend on dict iteration order at all."""
    from mcp.manager import _substitute_placeholder

    values = {"KEY2": "realsecretvalue", "KEY1": "abc{KEY2}xyz"}
    out = _substitute_placeholder("${KEY1:-}", values)
    assert out == "abc{KEY2}xyz"


def test_complete_pending_secrets_resolves_real_datadog_shaped_bash_placeholders():
    """Full chain for gap #2 (2026-08-07 milestone): a pending connection
    declaring secrets in real datadog-shaped "${VAR:-default}" syntax (not
    bare {VAR}) — missing_secrets already reports the bare names (as
    _missing_secrets_for_server/installer.py would have detected at install
    time) — must have EVERY declared "${VAR:-default}" span correctly
    substituted with the user-supplied value, not left as a literal
    unresolved string, when complete_pending_secrets runs."""
    from mcp.manager import complete_pending_secrets, _unregister

    pending = {
        "id": "plugin:dd-plugin:mcp",
        "name": "mcp",
        "transport": "http",
        "enabled": False,
        "cached_tools": [],
        "plugin_id": "dd-plugin",
        "missing_secrets": [
            "DD_MCP_DOMAIN",
            "DD_MCP_TOOLSETS",
            "DD_API_KEY",
            "DD_APPLICATION_KEY",
        ],
        "url": "https://${DD_MCP_DOMAIN:-not-setup}/v1/mcp?toolsets=${DD_MCP_TOOLSETS:-}",
        "auth_type": "none",
        "auth_value": "",
        "extra_headers": {
            "DD_API_KEY": "${DD_API_KEY:-}",
            "DD_APPLICATION_KEY": "${DD_APPLICATION_KEY:-}",
        },
    }
    connections = [pending]

    mock_client = MagicMock()
    mock_client.server_info.return_value = {"name": "mcp", "version": "1.0"}
    mock_client.list_tools.return_value = [
        {
            "name": "get_logs",
            "description": "Get logs",
            "inputSchema": {"type": "object", "properties": {}},
        }
    ]
    mock_client.call_probe.return_value = (False, "")

    values = {
        "DD_MCP_DOMAIN": "api.datadoghq.com",
        "DD_MCP_TOOLSETS": "logs,metrics",
        "DD_API_KEY": "dd-api-key-secret",
        "DD_APPLICATION_KEY": "dd-app-key-secret",
    }

    with (
        patch("mcp.manager.GenericMCPClient", return_value=mock_client),
        patch("mcp.manager._save_connections") as mock_save,
        patch("mcp.manager._load_connections", return_value=connections),
    ):
        result = complete_pending_secrets("plugin:dd-plugin:mcp", values)

    assert result["ok"] is True
    saved = mock_save.call_args_list[-1].args[0]
    conn = next(c for c in saved if c["id"] == "plugin:dd-plugin:mcp")
    assert conn["enabled"] is True
    assert conn["plugin_id"] == "dd-plugin"
    assert "missing_secrets" not in conn
    assert conn["url"] == "https://api.datadoghq.com/v1/mcp?toolsets=logs,metrics"
    assert conn["extra_headers"]["DD_API_KEY"] == "dd-api-key-secret"
    assert conn["extra_headers"]["DD_APPLICATION_KEY"] == "dd-app-key-secret"
    _unregister("plugin:dd-plugin:mcp")


# ---------------------------------------------------------------------------
# PR #10 review fix — credential leak via list_with_status(). command/args/url
# were returned unmasked; complete_pending_secrets substitutes real secrets
# into them. Now they're returned as _hint fields (masked).
# ---------------------------------------------------------------------------


def test_list_with_status_masks_secret_in_stdio_args():
    """A stdio connection whose args carry a substituted secret (e.g.
    ["--api-key", "sk-real-key"]) must NOT return the plaintext key in
    list_with_status(). The value following a --*-key flag must be masked."""
    from mcp.manager import list_with_status

    conn = {
        "id": "mcp-leaky",
        "name": "Leaky",
        "transport": "stdio",
        "enabled": True,
        "cached_tools": [],
        "command": "npx",
        "args": ["--api-key", "sk-real-secret-key-12345", "@server/mcp"],
        "env": {"TOKEN": "tok-secret"},
    }
    with patch("mcp.manager._load_connections", return_value=[conn]):
        rows = list_with_status()
    row = rows[0]
    # The old field names must be GONE — that was the leak vector.
    assert "command" not in row
    assert "args" not in row
    # The new _hint fields must be present and masked.
    assert row["command_hint"] == "npx"
    args_hint = row["args_hint"]
    assert args_hint[0] == "--api-key"
    # The value following --api-key must be masked, not the plaintext.
    assert args_hint[1] != "sk-real-secret-key-12345"
    assert "sk-real-secret-key-12345" not in args_hint[1]
    # The non-secret arg passes through verbatim.
    assert args_hint[2] == "@server/mcp"
    assert "sk-real-secret-key-12345" not in str(args_hint)


def test_list_with_status_masks_secret_in_http_url_query_param():
    """An http connection whose url carries a substituted secret as a query
    param (e.g. ?api_key=sk-real) must mask that param's value in
    list_with_status()."""
    from mcp.manager import list_with_status

    conn = {
        "id": "mcp-leaky-url",
        "name": "LeakyURL",
        "transport": "http",
        "enabled": True,
        "cached_tools": [],
        "url": "https://host/mcp?api_key=sk-real-secret-key-12345&toolsets=logs",
        "auth_type": "none",
        "auth_value": "",
        "extra_headers": {},
    }
    with patch("mcp.manager._load_connections", return_value=[conn]):
        rows = list_with_status()
    row = rows[0]
    assert "url" not in row
    assert "sk-real-secret-key-12345" not in row["url_hint"]
    # Non-secret query params and the host/path are preserved.
    assert "host/mcp" in row["url_hint"]
    assert "toolsets=logs" in row["url_hint"]
    # The api_key param is present but masked.
    assert "api_key=" in row["url_hint"]


def test_list_with_status_masks_secret_in_command_with_placeholder_syntax():
    """A stdio command that itself contains placeholder syntax (e.g.
    "{SECRET_EXE}") must be masked as a whole."""
    from mcp.manager import list_with_status

    conn = {
        "id": "mcp-leaky-cmd",
        "name": "LeakyCmd",
        "transport": "stdio",
        "enabled": True,
        "cached_tools": [],
        "command": "/path/to/{SECRET_EXE}",
        "args": [],
        "env": {},
    }
    with patch("mcp.manager._load_connections", return_value=[conn]):
        rows = list_with_status()
    row = rows[0]
    assert "{SECRET_EXE}" not in row["command_hint"]
    assert row["command_hint"]  # non-empty masked value


def test_url_hint_passes_through_url_with_no_secret_params():
    """A url with no secret-shaped query params must pass through verbatim
    (the UI needs the real host/path for display)."""
    from mcp.manager import _url_hint

    assert (
        _url_hint("https://host/mcp?toolsets=logs,metrics")
        == "https://host/mcp?toolsets=logs,metrics"
    )
    assert _url_hint("https://host/mcp") == "https://host/mcp"
    assert _url_hint("") == ""


def test_args_hint_masks_value_following_password_flag():
    """--password and --token flags must also have their following value
    masked, not just --api-key."""
    from mcp.manager import _args_hint

    out = _args_hint(
        ["--password", "my-secret-pass", "--verbose", "--token", "tok-abc"]
    )
    assert out[0] == "--password"
    assert out[1] != "my-secret-pass"
    assert "my-secret-pass" not in out[1]
    assert out[2] == "--verbose"
    assert out[3] == "--token"
    assert out[4] != "tok-abc"
    assert "tok-abc" not in out[4]
