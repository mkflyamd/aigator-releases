"""Pins what a local folder import does today, for every kind of folder users bring.

These tests describe the behavior before MCP launch inference existed and must keep
passing unchanged: a folder that does not match the inference rule keeps the same preview
lines, the same digest, the same index entry and registers no MCP server. FOLDERS holds
every kind that must stay that way; the one kind that now matches is in test_mcp_inference.
"""
import base64
import importlib
import json
from unittest.mock import patch

import pytest

SKILL_MD = b"---\nname: Folder Skill\ndescription: d\n---\n# Folder\nDo it."

FASTMCP_SERVER = b"""from fastmcp import FastMCP

server = FastMCP("demo")


@server.tool()
def ping() -> str:
    return "pong"


if __name__ == "__main__":
    server.run(transport="stdio")
"""

CLI_SCRIPT = b"""import argparse

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("name")
    print(p.parse_args().name)
"""

PYPROJECT = b"""[project]
name = "demo"
version = "1.0.0"
requires-python = ">=3.11,<3.13"
dependencies = ["fastmcp>=3.2.0,<4.0.0"]
"""

MCP_JSON = json.dumps({"mcpServers": {"srv": {"command": "npx", "args": ["x"]}}}).encode()

MCP_CLIENT = b"""from mcp import ClientSession, StdioServerParameters

if __name__ == "__main__":
    print(ClientSession, StdioServerParameters)
"""

FOLDERS = {
    "plain": {"SKILL.md": SKILL_MD},
    "tools_py": {"SKILL.md": SKILL_MD, "tools.py": b"TOOL_DEFS = []"},
    "fastmcp_server_no_pyproject": {"SKILL.md": SKILL_MD, "scripts/main.py": FASTMCP_SERVER},
    "fastmcp_test_file": {
        "SKILL.md": SKILL_MD, "scripts/test_server.py": FASTMCP_SERVER, "pyproject.toml": PYPROJECT,
    },
    "fastmcp_two_servers": {
        "SKILL.md": SKILL_MD, "a.py": FASTMCP_SERVER, "b.py": FASTMCP_SERVER, "pyproject.toml": PYPROJECT,
    },
    "mcp_client": {"SKILL.md": SKILL_MD, "scripts/client.py": MCP_CLIENT, "pyproject.toml": PYPROJECT},
    "cli_script": {"SKILL.md": SKILL_MD, "scripts/tool.py": CLI_SCRIPT},
    "pyproject_only": {"SKILL.md": SKILL_MD, "pyproject.toml": PYPROJECT},
    "mcp_json": {"SKILL.md": SKILL_MD, ".mcp.json": MCP_JSON},
}

INDEX_KEYS = {"id", "version", "tier", "installed_at", "has_tools", "approved_at", "permissions"}


def _route_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.marketplace import router
    from security import verify_csrf

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_csrf] = lambda: None
    return TestClient(app)


def _payload(files: dict[str, bytes]) -> dict:
    return {
        "kind": "folder",
        "name": "my-folder",
        "files": [{"path": p, "b64": base64.b64encode(b).decode()} for p, b in files.items()],
    }


@pytest.fixture
def installer(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    monkeypatch.setattr("marketplace.installer.PLUGINS_DIR", tmp_path / "plugins")
    import marketplace.installer as inst

    importlib.reload(inst)
    return inst


def _import_folder(inst, files):
    client = _route_client()
    payload = _payload(files)
    with (
        patch("routes.marketplace.load_installed_skill_prompts"),
        patch("routes.marketplace.load_skill_tools"),
        patch("routes.marketplace.install_skill_md", wraps=inst.install_skill_md),
        patch("mcp.manager.register_plugin_mcp_server", return_value={"ok": True, "id": "x"}) as register,
        patch("marketplace.installer._warm_uv_cache"),
        patch("mcp.stdio_client.acquire_pooled") as acquire,
    ):
        first = client.post("/api/marketplace/install-local", json=payload)
        assert first.status_code == 200, first.text
        second = client.post(
            "/api/marketplace/install-local",
            json={**payload, "consent": True, "digest": first.json()["summary"]["digest"]},
        )
    return first.json(), second, register, acquire


@pytest.mark.parametrize("kind", sorted(FOLDERS))
def test_preview_digest_is_the_hash_of_the_files(installer, kind):
    from marketplace import permissions as P

    files = FOLDERS[kind]
    first, _, _, _ = _import_folder(installer, files)

    assert first["consent_required"] is True
    assert first["summary"]["digest"] == P.files_digest(files)


@pytest.mark.parametrize("kind", sorted(FOLDERS))
def test_install_registers_no_mcp_server_and_starts_no_process(installer, kind):
    _, second, register, acquire = _import_folder(installer, FOLDERS[kind])

    assert second.status_code == 200, second.text
    assert second.json()["ok"] is True
    register.assert_not_called()
    acquire.assert_not_called()


@pytest.mark.parametrize("kind", sorted(FOLDERS))
def test_install_writes_exactly_the_files_and_the_same_index_entry(installer, kind):
    files = FOLDERS[kind]
    _, second, _, _ = _import_folder(installer, files)

    skill_dir = installer.INSTALLED_SKILLS_DIR / second.json()["skill_id"]
    written = {p.relative_to(skill_dir).as_posix() for p in skill_dir.rglob("*") if p.is_file()}
    assert written == set(files)

    entry = next(e for e in installer.load_installed() if e["id"] == second.json()["skill_id"])
    assert set(entry) == INDEX_KEYS
    assert entry["tier"] == "Community"
    assert entry["has_tools"] is ("tools.py" in files)


@pytest.mark.parametrize("kind", [k for k in sorted(FOLDERS) if k != "mcp_json"])
def test_preview_names_no_mcp_server_for_folders_without_a_manifest(installer, kind):
    first, _, _, _ = _import_folder(installer, FOLDERS[kind])

    assert first["summary"]["mcp_servers"] == []
    assert not any("MCP server" in line for line in first["summary"]["lines"])


def test_preview_already_names_the_server_in_a_folder_mcp_json(installer):
    first, _, register, _ = _import_folder(installer, FOLDERS["mcp_json"])

    assert first["summary"]["mcp_servers"] == ["srv"]
    assert "Starts the MCP server 'srv' on your computer (not sandboxed): npx x" in first["summary"]["lines"]
    register.assert_not_called()


@pytest.mark.parametrize("kind", ["plain", "fastmcp_two_servers", "mcp_json"])
def test_uninstalling_a_local_skill_leaves_mcp_connections_alone(installer, kind):
    _, second, _, _ = _import_folder(installer, FOLDERS[kind])

    with patch("marketplace.installer._teardown_plugin_mcp") as teardown:
        result = installer.uninstall_skill(second.json()["skill_id"])

    assert result["ok"] is True
    teardown.assert_not_called()
    assert not (installer.INSTALLED_SKILLS_DIR / second.json()["skill_id"]).exists()
