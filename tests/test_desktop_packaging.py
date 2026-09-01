import json
from pathlib import Path

import yaml
from PIL import Image


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


def test_mac_icon_is_large_enough_for_electron_builder():
    """electron-builder rejects macOS icons smaller than 512x512 with
    "Icon must be at least 512x512 pixels", which fails the entire macOS
    release build and (because the checksums job used to need: build) blocked
    checksum publication for every platform. Guard the icon size here.
    """
    package = json.loads((ROOT / "shell" / "package.json").read_text(encoding="utf-8"))
    # mac.icon is relative to shell/package.json (e.g. "../build/aigator_icon_1024.png");
    # resolve it against the shell dir so the `..` is walked correctly.
    icon_path = (ROOT / "shell" / package["build"]["mac"]["icon"]).resolve()
    with Image.open(icon_path) as img:
        assert min(img.size) >= 512, (
            f"mac icon {icon_path.name} is {img.size[0]}x{img.size[1]}; "
            "electron-builder requires at least 512x512"
        )


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
    assert "npm ci --ignore-scripts" in workflow_text
    assert "Smoke-test packaged backend" in workflow_text
    assert "http://127.0.0.1:18765/health" in workflow_text


def test_release_workflow_publishes_checksums_on_partial_build_failure():
    """A single platform build failure must not block checksum publication for
    the platforms that did ship. The checksums job runs with `!cancelled()`
    (not the default `success()`) so a broken macOS build still produces a
    SHA256SUMS.txt covering the Windows/Linux packages.
    """
    workflow_path = ROOT / ".github" / "workflows" / "release-desktop.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    checksums = workflow["jobs"]["checksums"]
    if_expr = str(checksums.get("if", ""))
    assert "!cancelled()" in if_expr, (
        "checksums job must use `if: ${{ !cancelled() }}` so a partial build "
        "failure still publishes checksums for the platforms that shipped"
    )


def test_packaged_shell_uses_bundled_backend_sidecar():
    main = (ROOT / "shell" / "main.js").read_text(encoding="utf-8")

    assert "process.resourcesPath" in main
    assert "aigator-backend.exe" in main
    assert "app.isPackaged ? 8000 : 8002" in main
    assert "backendEnv.TMPDIR = runtimeDir" in main
    assert "pyProc.kill()" in main
