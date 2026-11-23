"""A locally imported skill that ships a Python MCP server is shown, approved and
registered without any setup script."""
import base64
import importlib
import json
from unittest.mock import MagicMock, patch

import pytest

from marketplace import permissions as P
from marketplace.mcp_inference import infer_launch_spec

SKILL_MD = b"---\nname: Snowflake MCP\ndescription: d\n---\n# Snowflake\nQuery it."

SERVER = b"""from fastmcp import FastMCP

server = FastMCP("snowflake")


@server.tool()
def ping() -> str:
    return "pong"


if __name__ == "__main__":
    server.run(transport="stdio")
"""

PYPROJECT = b"""[project]
name = "snowflake-mcp"
version = "1.0.2"
requires-python = ">=3.11,<3.13"
dependencies = ["fastmcp>=3.2.0,<4.0.0", "click>=8.0.0"]

[project.scripts]
snowflake-mcp = "snowflake_mcp.main:main"

[build-system]
requires = ["not a real backend"]
build-backend = "does.not.exist"
"""

FILES = {"SKILL.md": SKILL_MD, "scripts/main.py": SERVER, "pyproject.toml": PYPROJECT}
EXPECTED_ARGS = [
    "run", "--no-project", "--python", ">=3.11,<3.13",
    "--with=fastmcp>=3.2.0,<4.0.0", "--with=click>=8.0.0", "scripts/main.py",
]


def test_the_snowflake_layout_infers_a_uv_launch():
    spec = infer_launch_spec(FILES)

    assert spec is not None
    assert spec.name == "snowflake-mcp"
    assert spec.command == "uv"
    assert spec.args() == EXPECTED_ARGS


WRAPPED_SERVER = b"""import click
from fastmcp import FastMCP

server = FastMCP("snowflake")


@click.command()
def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
"""


def test_a_server_started_by_a_main_function_the_guard_calls_matches():
    spec = infer_launch_spec({**FILES, "scripts/main.py": WRAPPED_SERVER})

    assert spec is not None and spec.args() == EXPECTED_ARGS


def test_a_guard_that_calls_a_function_which_never_runs_the_server_does_not_match():
    idle = WRAPPED_SERVER.replace(b'server.run(transport="stdio")', b"print('hi')")

    assert infer_launch_spec({**FILES, "scripts/main.py": idle}) is None


def test_inference_is_a_pure_function_of_the_files():
    assert infer_launch_spec(FILES) == infer_launch_spec(dict(reversed(list(FILES.items()))))


def test_python_pin_is_left_out_when_the_project_declares_none():
    pyproject = PYPROJECT.replace(b'requires-python = ">=3.11,<3.13"\n', b"")

    spec = infer_launch_spec({**FILES, "pyproject.toml": pyproject})

    assert "--python" not in spec.args()


@pytest.mark.parametrize(
    "changes",
    [
        {"pyproject.toml": b'[project]\nname = "x"\ndependencies = ["click"]\n'},
        {"pyproject.toml": b'[project]\nname = "x"\ndependencies = []\n'},
        {"pyproject.toml": b'[project]\nname = "x"\ndependencies = ["fastmcp", "--index-url=http://evil"]\n'},
        {"pyproject.toml": b'[project]\nname = "x"\ndependencies = ["fastmcp\\nclick"]\n'},
        {"pyproject.toml": b'[project]\nname = "x"\nrequires-python = "-1"\ndependencies = ["fastmcp"]\n'},
        {"pyproject.toml": b"this is not toml ["},
        {"scripts/main.py": b"def broken(:\n"},
        {"scripts/main.py": SERVER.replace(b'if __name__ == "__main__":\n    server.run(transport="stdio")', b"server.run()")},
        {"scripts/main.py": SERVER.replace(b"FastMCP(", b"make(")},
        {"scripts/main.py": SERVER.replace(b"from fastmcp import FastMCP", b"FastMCP = dict")},
        {"scripts/main.py": SERVER.replace(b"server.run(", b"server.go(")},
    ],
)
def test_files_that_do_not_fit_the_rule_infer_nothing(changes):
    assert infer_launch_spec({**FILES, **changes}) is None


def test_a_folder_without_a_pyproject_infers_nothing():
    assert infer_launch_spec({k: v for k, v in FILES.items() if k != "pyproject.toml"}) is None


def test_the_low_level_mcp_server_api_also_matches():
    low_level = b"""from mcp.server import Server

app = Server("demo")

if __name__ == "__main__":
    app.run()
"""
    pyproject = b'[project]\nname = "x"\ndependencies = ["mcp[cli]>=1.27"]\n'

    spec = infer_launch_spec({"SKILL.md": SKILL_MD, "srv.py": low_level, "pyproject.toml": pyproject})

    assert spec is not None and spec.entry == "srv.py"


@pytest.mark.parametrize("path", ["tests/server.py", ".venv/server.py", "node_modules/x/server.py", "scripts/test_main.py"])
def test_server_files_in_test_and_environment_folders_are_ignored(path):
    files = {"SKILL.md": SKILL_MD, path: SERVER, "pyproject.toml": PYPROJECT}

    assert infer_launch_spec(files) is None


def test_two_server_files_are_ambiguous():
    assert infer_launch_spec({**FILES, "scripts/other.py": SERVER}) is None


def test_a_test_file_next_to_the_server_does_not_make_it_ambiguous():
    assert infer_launch_spec({**FILES, "scripts/test_main.py": SERVER}).entry == "scripts/main.py"


def test_the_preview_lists_the_server_command_and_packages():
    summary = P.summarize_package(FILES)

    assert summary["mcp_servers"] == ["snowflake-mcp"]
    assert (
        "Starts the MCP server 'snowflake-mcp' on your computer (not sandboxed): "
        "uv run --no-project --python >=3.11,<3.13 --with=fastmcp>=3.2.0,<4.0.0 --with=click>=8.0.0 scripts/main.py"
    ) in summary["lines"]
    assert (
        "Downloads and installs these Python packages the first time it starts: fastmcp>=3.2.0,<4.0.0, click>=8.0.0"
    ) in summary["lines"]
    assert summary["digest"] == P.files_digest(FILES)


def test_the_preview_says_so_when_policy_blocks_the_server():
    policy = MagicMock(block_bundle_stdio_mcp=True)
    with patch("sandbox.policy.load_policy", return_value=policy):
        summary = P.summarize_package(FILES)

    assert any(line.startswith("Blocked by your administrator's policy") for line in summary["lines"])
    assert not any("Downloads and installs" in line for line in summary["lines"])


def test_a_declared_mcp_json_wins_over_inference():
    files = {**FILES, ".mcp.json": json.dumps({"mcpServers": {"srv": {"command": "npx", "args": ["x"]}}}).encode()}

    summary = P.summarize_package(files)

    assert summary["mcp_servers"] == ["srv"]
    assert not any("Downloads and installs" in line for line in summary["lines"])


# ── through the real route ───────────────────────────────────────────────────


def _route_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.marketplace import router
    from security import verify_csrf

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_csrf] = lambda: None
    return TestClient(app)


@pytest.fixture
def installer(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    monkeypatch.setattr("marketplace.installer.PLUGINS_DIR", tmp_path / "plugins")
    import marketplace.installer as inst

    importlib.reload(inst)
    return inst


def _import(inst, files, register_result=None):
    client = _route_client()
    payload = {
        "kind": "folder",
        "name": "snowflake-mcp",
        "files": [{"path": p, "b64": base64.b64encode(b).decode()} for p, b in files.items()],
    }
    result = register_result or {"ok": True, "id": "plugin:snowflake-mcp:snowflake-mcp", "enabled": True}
    with (
        patch("routes.marketplace.load_installed_skill_prompts"),
        patch("routes.marketplace.load_skill_tools"),
        patch("mcp.manager.register_plugin_mcp_server", return_value=result) as register,
        patch("marketplace.installer._warm_uv_cache") as warm,
    ):
        first = client.post("/api/marketplace/install-local", json=payload)
        assert first.status_code == 200, first.text
        register.assert_not_called()
        warm.assert_not_called()
        second = client.post(
            "/api/marketplace/install-local",
            json={**payload, "consent": True, "digest": first.json()["summary"]["digest"]},
        )
    return first.json(), second, register, warm


def test_approving_the_import_registers_the_server_in_the_skill_folder(installer):
    _, second, register, warm = _import(installer, FILES)

    assert second.status_code == 200, second.text
    skill_id = second.json()["skill_id"]
    skill_dir = installer.INSTALLED_SKILLS_DIR / skill_id
    register.assert_called_once()
    owner, server_name, provisional, missing = register.call_args.args
    assert (owner, server_name, missing) == (skill_id, "snowflake-mcp", [])
    assert provisional == {
        "transport": "stdio",
        "command": "uv",
        "args": EXPECTED_ARGS,
        "env": {},
        "name": "snowflake-mcp",
        "cwd": str(skill_dir),
    }
    warm.assert_called_once()
    assert warm.call_args.args[1] == skill_dir
    assert second.json()["mcp_connection_ids"] == ["plugin:snowflake-mcp:snowflake-mcp"]
    entry = next(e for e in installer.load_installed() if e["id"] == skill_id)
    assert entry["mcp_connection_ids"] == ["plugin:snowflake-mcp:snowflake-mcp"]
    assert entry["tier"] == "Community"


def test_a_server_that_cannot_start_is_reported_and_still_recorded_for_cleanup(installer):
    failed = {"ok": False, "id": "plugin:snowflake-mcp:snowflake-mcp", "error": "uv isn't installed"}

    _, second, _, _ = _import(installer, FILES, register_result=failed)

    body = second.json()
    assert body["ok"] is True
    assert body["mcp_error"] == "uv isn't installed"
    entry = next(e for e in installer.load_installed() if e["id"] == body["skill_id"])
    assert entry["mcp_connection_ids"] == ["plugin:snowflake-mcp:snowflake-mcp"]


def test_a_registration_crash_does_not_fail_the_import(installer):
    client = _route_client()
    payload = {
        "kind": "folder",
        "name": "x",
        "files": [{"path": p, "b64": base64.b64encode(b).decode()} for p, b in FILES.items()],
    }
    with (
        patch("routes.marketplace.load_installed_skill_prompts"),
        patch("routes.marketplace.load_skill_tools"),
        patch("mcp.manager.register_plugin_mcp_server", side_effect=RuntimeError("boom")),
        patch("marketplace.installer._warm_uv_cache"),
    ):
        digest = client.post("/api/marketplace/install-local", json=payload).json()["summary"]["digest"]
        second = client.post("/api/marketplace/install-local", json={**payload, "consent": True, "digest": digest})

    assert second.status_code == 200
    assert second.json()["mcp_error"] == "boom"


def test_uninstalling_stops_the_server_before_deleting_its_folder(installer):
    _, second, _, _ = _import(installer, FILES)
    skill_id = second.json()["skill_id"]
    skill_dir = installer.INSTALLED_SKILLS_DIR / skill_id
    seen = {}

    def teardown(plugin_id):
        seen["id"] = plugin_id
        seen["folder_still_there"] = skill_dir.exists()

    with patch("marketplace.installer._teardown_plugin_mcp", side_effect=teardown):
        result = installer.uninstall_skill(skill_id)

    assert result["ok"] is True
    assert seen == {"id": skill_id, "folder_still_there": True}
    assert not skill_dir.exists()


def test_the_server_is_owned_by_the_skill_so_teardown_removes_it(installer):
    from mcp import manager

    removed = []
    with patch.object(manager, "remove", side_effect=lambda cid: removed.append(cid) or {"ok": True}), \
            patch.object(manager, "_load_connections", return_value=[
                {"id": "plugin:s:s", "plugin_id": "s"},
                {"id": "other", "plugin_id": "someone-else"},
            ]):
        manager.remove_plugin_mcp_servers("s")

    assert removed == ["plugin:s:s"]


# ── the skill and its server are used together ───────────────────────────────

CONNECTION = "plugin:snowflake-mcp:snowflake-mcp"


@pytest.fixture
def deps_map():
    import shared

    saved = dict(shared.SKILL_DEPENDENCIES_MAP)
    shared.SKILL_DEPENDENCIES_MAP.clear()
    yield shared.SKILL_DEPENDENCIES_MAP
    shared.SKILL_DEPENDENCIES_MAP.clear()
    shared.SKILL_DEPENDENCIES_MAP.update(saved)


def _entry(**extra):
    return {"id": "snowflake-mcp", "tier": "Community", **extra}


def test_a_skill_with_an_inferred_server_depends_on_that_connection(deps_map):
    from marketplace import loader

    with patch("marketplace.state.get_entry", return_value=_entry(mcp_connection_ids=[CONNECTION])):
        loader.link_skill_mcp_connections("snowflake-mcp")

    assert [d["id"] for d in deps_map["snowflake-mcp"]] == [CONNECTION]


def test_linking_keeps_the_dependencies_the_skill_already_has_and_is_repeatable(deps_map):
    from marketplace import loader

    deps_map["snowflake-mcp"] = [{"id": "shell_runner", "reason": "r"}]
    with patch("marketplace.state.get_entry", return_value=_entry(mcp_connection_ids=[CONNECTION])):
        loader.link_skill_mcp_connections("snowflake-mcp")
        loader.link_skill_mcp_connections("snowflake-mcp")

    assert [d["id"] for d in deps_map["snowflake-mcp"]] == ["shell_runner", CONNECTION]


@pytest.mark.parametrize(
    "entry",
    [
        None,
        _entry(),
        _entry(mcp_connection_ids=[]),
        _entry(skill_ids=["inner"], mcp_connection_ids=[CONNECTION]),
    ],
)
def test_other_skills_and_plugin_bundles_are_left_alone(deps_map, entry):
    from marketplace import loader

    with patch("marketplace.state.get_entry", return_value=entry):
        loader.link_skill_mcp_connections("snowflake-mcp")

    assert deps_map == {}


def test_choosing_the_skill_offers_the_servers_tools(deps_map):
    import shared
    from marketplace import loader
    from routes import chat

    tools = [{"name": "snowflake_query"}, {"name": "unrelated"}]
    with patch.dict(shared.SKILL_TOOLS_MAP, {CONNECTION: {"snowflake_query"}}),             patch.object(shared, "TOOLS", tools),             patch("marketplace.state.get_entry", return_value=_entry(mcp_connection_ids=[CONNECTION])):
        before = chat._filter_tools("snowflake-mcp", False, active_skills=["snowflake-mcp"])
        loader.link_skill_mcp_connections("snowflake-mcp")
        after = chat._filter_tools("snowflake-mcp", False, active_skills=["snowflake-mcp"])

    assert "snowflake_query" not in [t["name"] for t in before]
    assert [t["name"] for t in after if t["name"] in {"snowflake_query", "unrelated"}] == ["snowflake_query"]
