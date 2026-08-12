import json
from pathlib import Path

import yaml


ROOT = Path(__file__).parent.parent


def test_electron_builder_bundles_backend_and_platform_targets():
    package = json.loads((ROOT / "shell" / "package.json").read_text(encoding="utf-8"))
    build = package["build"]
    version = (ROOT / "version.txt").read_text(encoding="utf-8").strip()

    assert package["version"] == version
    assert package["devDependencies"]["electron-builder"]
    assert {entry["to"] for entry in build["extraResources"]} >= {"backend", "tray/aigator_icon.png"}
    assert build["win"]["target"] == ["nsis"]
    assert set(build["mac"]["target"]) == {"dmg", "zip"}
    assert set(build["linux"]["target"]) == {"AppImage", "deb"}


def test_release_workflow_builds_every_supported_platform():
    workflow_path = ROOT / ".github" / "workflows" / "release-desktop.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)
    includes = workflow["jobs"]["build"]["strategy"]["matrix"]["include"]

    assert {entry["name"] for entry in includes} == {
        "Windows x64",
        "macOS x64",
        "macOS arm64",
        "Linux x64",
    }
    assert workflow[True]["release"]["types"] == ["published"]
    assert "astral-sh/setup-uv@" in workflow_text
    assert "uv sync --locked" in workflow_text
    assert "uv run python packaging/sync_version.py" in workflow_text
    assert "uv run pyinstaller" in workflow_text


def test_packaged_shell_uses_bundled_backend_sidecar():
    main = (ROOT / "shell" / "main.js").read_text(encoding="utf-8")

    assert "process.resourcesPath" in main
    assert "aigator-backend.exe" in main
    assert "app.isPackaged ? 8000 : 8002" in main
    assert "backendEnv.TMPDIR = runtimeDir" in main
    assert "pyProc.kill()" in main
