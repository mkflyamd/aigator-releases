import json
from pathlib import Path

import yaml


ROOT = Path(__file__).parent.parent


def test_electron_builder_bundles_backend_and_platform_targets():
    package = json.loads((ROOT / "shell" / "package.json").read_text(encoding="utf-8"))
    build = package["build"]

    assert package["devDependencies"]["electron-builder"]
    assert {entry["to"] for entry in build["extraResources"]} >= {"backend", "tray/aigator_icon.png"}
    assert build["win"]["target"] == ["nsis"]
    assert set(build["mac"]["target"]) == {"dmg", "zip"}
    assert set(build["linux"]["target"]) == {"AppImage", "deb"}


def test_release_workflow_builds_every_supported_platform():
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "release-desktop.yml").read_text(encoding="utf-8")
    )
    includes = workflow["jobs"]["build"]["strategy"]["matrix"]["include"]

    assert {entry["name"] for entry in includes} == {
        "Windows x64",
        "macOS x64",
        "macOS arm64",
        "Linux x64",
    }
    assert workflow[True]["release"]["types"] == ["published"]


def test_packaged_shell_uses_bundled_backend_sidecar():
    main = (ROOT / "shell" / "main.js").read_text(encoding="utf-8")

    assert "process.resourcesPath" in main
    assert "aigator-backend.exe" in main
    assert "app.isPackaged ? 8000 : 8002" in main
    assert "pyProc.kill()" in main
