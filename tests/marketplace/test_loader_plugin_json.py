import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "web"))

import json
from pathlib import Path

import pytest


def test_load_plugin_json_returns_manifest(tmp_path):
    plugin_dir = tmp_path / ".claude-plugin"
    plugin_dir.mkdir()
    manifest = {
        "name": "rocm-toolkit",
        "version": "1.2.0",
        "description": "GPU diagnostics",
        "gator": {"tier": "native", "gateway_required": True},
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")

    from marketplace.loader import load_plugin_manifest

    result = load_plugin_manifest(tmp_path)
    assert result["name"] == "rocm-toolkit"
    assert result["gator"]["tier"] == "native"


def test_load_plugin_json_falls_back_to_frontmatter(tmp_path):
    """When no plugin.json exists, returns minimal dict from SKILL.md frontmatter."""
    skill_md = "---\nname: basic-skill\ndescription: A simple skill\nversion: 1.0\n---\n\nDo stuff."
    (tmp_path / "SKILL.md").write_text(skill_md, encoding="utf-8")

    from marketplace.loader import load_plugin_manifest

    result = load_plugin_manifest(tmp_path)
    assert result["name"] == "basic-skill"
    assert result.get("gator") is None  # no gator block in SKILL.md


def test_load_plugin_json_missing_both_returns_empty(tmp_path):
    from marketplace.loader import load_plugin_manifest

    result = load_plugin_manifest(tmp_path)
    assert isinstance(result, dict)
    assert result == {}


def test_load_plugin_json_ignores_malformed_json(tmp_path):
    plugin_dir = tmp_path / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text("{ not valid json }", encoding="utf-8")

    from marketplace.loader import load_plugin_manifest

    result = load_plugin_manifest(tmp_path)
    assert result == {}


def test_load_plugin_json_ignores_non_object_json(tmp_path):
    """Valid JSON that isn't an object (list, string, null) must not leak through as a non-dict."""
    plugin_dir = tmp_path / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text("[]", encoding="utf-8")

    from marketplace.loader import load_plugin_manifest

    result = load_plugin_manifest(tmp_path)
    assert result == {}


def test_load_plugin_json_frontmatter_crlf(tmp_path):
    """SKILL.md with Windows CRLF line endings must still parse."""
    skill_md = "---\r\nname: crlf-skill\r\ndescription: shipped from Windows\r\n---\r\n\r\nBody."
    (tmp_path / "SKILL.md").write_bytes(skill_md.encode("utf-8"))

    from marketplace.loader import load_plugin_manifest

    result = load_plugin_manifest(tmp_path)
    assert result["name"] == "crlf-skill"


import os


@pytest.fixture(autouse=True)
def _clean_bin_paths():
    import shared

    shared.SKILL_BIN_PATHS.clear()
    yield
    shared.SKILL_BIN_PATHS.clear()


def test_bin_dir_is_tracked_but_never_put_on_the_app_path(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "rocm-smi").write_text("#!/bin/sh\necho ok")

    original_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", original_path)

    import shared
    from marketplace.loader import inject_bin_path

    inject_bin_path(tmp_path, skill_id="my-skill")
    assert shared.SKILL_BIN_PATHS["my-skill"] == str(bin_dir)
    assert os.environ["PATH"] == original_path


def test_bin_dir_registration_is_idempotent(tmp_path, monkeypatch):
    (tmp_path / "bin").mkdir()
    monkeypatch.setenv("PATH", "/usr/bin")

    import shared
    from marketplace.loader import inject_bin_path

    inject_bin_path(tmp_path, skill_id="my-skill")
    inject_bin_path(tmp_path, skill_id="my-skill")  # call twice

    assert shared.SKILL_BIN_PATHS == {"my-skill": str(tmp_path / "bin")}
    assert os.environ["PATH"] == "/usr/bin"


def test_no_bin_dir_is_noop(tmp_path, monkeypatch):
    original_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", original_path)

    import shared
    from marketplace.loader import inject_bin_path

    inject_bin_path(tmp_path, skill_id="my-skill")  # tmp_path has no bin/ subdir
    assert os.environ["PATH"] == original_path
    assert "my-skill" not in shared.SKILL_BIN_PATHS


def test_bin_dir_forgotten_on_unload(tmp_path, monkeypatch):
    """Unloading a skill must drop its bin dir so a disabled or uninstalled
    plugin's shims are no longer offered to sandboxed shells."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", "/usr/bin")

    import shared
    from marketplace.loader import inject_bin_path, _remove_bin_path

    inject_bin_path(tmp_path, skill_id="my-skill")
    assert shared.SKILL_BIN_PATHS.get("my-skill") == str(bin_dir)

    _remove_bin_path("my-skill")
    assert "my-skill" not in shared.SKILL_BIN_PATHS
    assert os.environ["PATH"] == "/usr/bin"


def test_concurrent_inject_bin_path_no_drops(tmp_path, monkeypatch):
    """20 threads each registering a distinct bin dir must end with all 20 tracked
    and the app's PATH untouched."""
    import threading

    monkeypatch.setenv("PATH", "/usr/bin")

    bin_dirs = []
    for i in range(20):
        d = tmp_path / f"skill-{i}"
        (d / "bin").mkdir(parents=True)
        bin_dirs.append(d)

    import shared
    from marketplace.loader import inject_bin_path

    threads = [
        threading.Thread(target=inject_bin_path, args=(d, f"s{i}"))
        for i, d in enumerate(bin_dirs)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for i, d in enumerate(bin_dirs):
        assert shared.SKILL_BIN_PATHS[f"s{i}"] == str(d / "bin")
    assert os.environ["PATH"] == "/usr/bin"


def test_load_skill_tools_leaves_the_app_path_byte_identical(tmp_path, monkeypatch):
    skill_dir = tmp_path / "shimmed"
    (skill_dir / "bin").mkdir(parents=True)
    (skill_dir / "bin" / "uvx.cmd").write_text("@echo pwned")
    skill_md = "---\nname: shimmed\ndescription: d\n---\nBody."
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
    before = os.environ.get("PATH", "")

    import shared
    from marketplace import loader, state

    monkeypatch.setattr(state, "is_disabled", lambda sid: False)
    result = loader.load_skill_tools("shimmed", skill_dir, "Community")

    assert result == {"ok": True}
    assert os.environ.get("PATH", "") == before
    assert shared.SKILL_BIN_PATHS["shimmed"] == str(skill_dir / "bin")


def test_enabled_skill_bin_dirs_skips_disabled_skills(monkeypatch):
    import shared
    from marketplace import loader, state

    shared.SKILL_BIN_PATHS.update({"on": "/skills/on/bin", "off": "/skills/off/bin"})
    monkeypatch.setattr(state, "disabled_ids", lambda: {"off"})

    assert loader.enabled_skill_bin_dirs() == ["/skills/on/bin"]


from unittest.mock import patch, MagicMock


def test_mcp_json_starts_server_on_skill_load(tmp_path):
    mcp_config = {
        "mcpServers": {"my-server": {"command": "python", "args": ["-m", "myserver"]}}
    }
    import json as _json

    (tmp_path / ".mcp.json").write_text(_json.dumps(mcp_config))

    with patch("marketplace.loader.start_plugin_mcp") as mock_start:
        from marketplace.loader import load_plugin_mcp

        load_plugin_mcp("test-skill", tmp_path)
        mock_start.assert_called_once_with("test-skill", mcp_config["mcpServers"])


def test_no_mcp_json_is_noop(tmp_path):
    with patch("marketplace.loader.start_plugin_mcp") as mock_start:
        from marketplace.loader import load_plugin_mcp

        load_plugin_mcp("test-skill", tmp_path)
        mock_start.assert_not_called()


def test_mcp_servers_not_tracked_when_start_fails(tmp_path):
    """If start_plugin_mcp returns False, the tracking dict must stay empty —
    otherwise unload will try to stop servers that never started."""
    import json as _json

    mcp_config = {"mcpServers": {"phantom": {"command": "x"}}}
    (tmp_path / ".mcp.json").write_text(_json.dumps(mcp_config))

    from marketplace import loader

    loader._PLUGIN_MCP_SERVERS.pop("test-skill", None)
    with patch("marketplace.loader.start_plugin_mcp", return_value=False):
        loader.load_plugin_mcp("test-skill", tmp_path)
    assert "test-skill" not in loader._PLUGIN_MCP_SERVERS


def test_unload_plugin_mcp_stops_each_tracked_server(tmp_path):
    """unload_plugin_mcp must call stop_plugin_mcp for every tracked server name."""
    from marketplace import loader

    loader._PLUGIN_MCP_SERVERS["test-skill"] = ["server-a", "server-b"]
    with patch("marketplace.loader.stop_plugin_mcp") as mock_stop:
        loader.unload_plugin_mcp("test-skill")
    assert mock_stop.call_count == 2
    mock_stop.assert_any_call("test-skill", "server-a")
    mock_stop.assert_any_call("test-skill", "server-b")
    assert "test-skill" not in loader._PLUGIN_MCP_SERVERS


def test_load_plugin_mcp_runs_for_skill_md_only_plugin(tmp_path, monkeypatch):
    """A plugin with .mcp.json but no tools.py must still get its MCP servers started
    — the early return in load_skill_tools for missing tools.py must not skip MCP wiring."""
    import json as _json

    mcp_config = {"mcpServers": {"my-server": {"command": "python"}}}
    (tmp_path / ".mcp.json").write_text(_json.dumps(mcp_config))
    # Deliberately no tools.py

    with patch("marketplace.loader.start_plugin_mcp", return_value=True) as mock_start:
        from marketplace.loader import load_skill_tools

        result = load_skill_tools("mcp-only-skill", tmp_path, "Verified")
    assert result["ok"] is True
    mock_start.assert_called_once_with("mcp-only-skill", mcp_config["mcpServers"])
