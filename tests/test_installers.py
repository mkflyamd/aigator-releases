import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

import pytest


ROOT = Path(__file__).parent.parent
PACKAGE_CONTENT = b"verified installer fixture\n"
PACKAGE_HASH = hashlib.sha256(PACKAGE_CONTENT).hexdigest()


def _unix_asset() -> tuple[str, str, str]:
    if platform.system() == "Darwin":
        architecture = "arm64" if platform.machine() == "arm64" else "x64"
        return f"AI-Gator-9.8.7-macOS-{architecture}.dmg", "macos", architecture
    return "AI-Gator-9.8.7-Linux-x64.AppImage", "linux", "x64"


def _release(asset_name: str, *, digest: str = "", checksum_url: str = "") -> list[dict]:
    assets = [
        {
            "name": asset_name,
            "browser_download_url": "https://example.test/package",
            "size": len(PACKAGE_CONTENT),
            "digest": digest,
        }
    ]
    if checksum_url:
        assets.append(
            {
                "name": "SHA256SUMS.txt",
                "browser_download_url": checksum_url,
                "size": 80,
            }
        )
    return [
        {"tag_name": "v0.0.0-draft", "draft": True, "prerelease": False, "assets": []},
        {"tag_name": "v9.8.7", "draft": False, "prerelease": False, "assets": assets},
    ]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)


def _run_shell_installer(tmp_path: Path, monkeypatch, releases: list[dict]):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    release_json = json.dumps(releases)
    _write_executable(
        fake_bin / "curl",
        """#!/usr/bin/env python3
import os
from pathlib import Path
import sys

output = Path(sys.argv[sys.argv.index('--output') + 1])
url = next(value for value in sys.argv[1:] if value.startswith('https://'))
if 'api.github.com' in url:
    output.write_text(os.environ['INSTALLER_RELEASE_JSON'], encoding='utf-8')
elif url.endswith('/checksums'):
    output.write_text(os.environ['INSTALLER_CHECKSUMS'], encoding='utf-8')
else:
    output.write_bytes(os.environ['INSTALLER_PACKAGE'].encode())
""",
    )
    monkeypatch.setenv("AIGATOR_INSTALLER_CURL", str(fake_bin / "curl"))
    monkeypatch.setenv("INSTALLER_RELEASE_JSON", release_json)
    monkeypatch.setenv("INSTALLER_PACKAGE", PACKAGE_CONTENT.decode())
    monkeypatch.setenv("INSTALLER_CHECKSUMS", f"{PACKAGE_HASH}  {_unix_asset()[0]}\n")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_BIN_HOME", str(tmp_path / "bin-destination"))
    return subprocess.run(
        ["bash", str(ROOT / "Get-AIGator.sh"), "--dry-run"],
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(os.name == "nt", reason="Bash installer runs on Unix hosts")
def test_shell_installer_dry_run_selects_and_verifies_asset_digest(tmp_path, monkeypatch):
    asset_name, expected_platform, expected_architecture = _unix_asset()
    releases = _release(asset_name, digest=f"sha256:{PACKAGE_HASH}")

    result = _run_shell_installer(tmp_path, monkeypatch, releases)

    assert result.returncode == 0, result.stderr
    assert f"Selected release v9.8.7 for {expected_platform} {expected_architecture}" in result.stdout
    assert "Checksum verified" in result.stdout
    assert "Dry run completed without installing or launching AI Gator" in result.stdout
    assert not (tmp_path / "data").exists()


@pytest.mark.skipif(os.name == "nt", reason="Bash installer runs on Unix hosts")
def test_shell_installer_dry_run_accepts_checksum_file(tmp_path, monkeypatch):
    releases = _release(
        _unix_asset()[0],
        checksum_url="https://example.test/checksums",
    )

    result = _run_shell_installer(tmp_path, monkeypatch, releases)

    assert result.returncode == 0, result.stderr
    assert "Downloading SHA256SUMS.txt" in result.stdout
    assert "Checksum verified" in result.stdout


@pytest.mark.skipif(os.name == "nt", reason="Bash installer runs on Unix hosts")
def test_shell_installer_dry_run_rejects_digest_mismatch(tmp_path, monkeypatch):
    releases = _release(_unix_asset()[0], digest=f"sha256:{'0' * 64}")

    result = _run_shell_installer(tmp_path, monkeypatch, releases)

    assert result.returncode == 1
    assert "Checksum verification failed" in result.stderr
    assert "Dry run completed" not in result.stdout


@pytest.mark.skipif(os.name != "nt", reason="PowerShell installer runs on Windows")
def test_windows_installer_dry_run_selects_and_verifies_asset_digest(tmp_path, monkeypatch):
    releases = _release(
        "AI-Gator-9.8.7-Windows-x64.exe", digest=f"sha256:{PACKAGE_HASH}"
    )
    release_path = tmp_path / "releases.json"
    release_path.write_text(json.dumps(releases), encoding="utf-8")
    package_path = tmp_path / "package.exe"
    package_path.write_bytes(PACKAGE_CONTENT)
    wrapper = tmp_path / "run-installer.ps1"
    wrapper.write_text(
        f"""$env:PROCESSOR_ARCHITECTURE = 'AMD64'
function global:Invoke-RestMethod {{ Get-Content -Raw '{release_path}' | ConvertFrom-Json }}
function global:Invoke-WebRequest {{ param($Uri, $Headers, $OutFile, $UseBasicParsing) Copy-Item '{package_path}' $OutFile }}
try {{
    & '{ROOT / "Get-AIGator.ps1"}' -DryRun
}}
catch {{
    Write-Error $_
    exit 1
}}
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(wrapper)], capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
    assert "Selected latest published release v9.8.7" in result.stdout
    assert "Checksum verified" in result.stdout
    assert "Dry run completed without starting the installer" in result.stdout


def test_installer_scripts_expose_dry_run_without_skipping_verification():
    powershell = (ROOT / "Get-AIGator.ps1").read_text(encoding="utf-8")
    shell = (ROOT / "Get-AIGator.sh").read_text(encoding="utf-8")

    assert "[switch]$DryRun" in powershell
    assert powershell.index('Log "OK" "Checksum verified"') < powershell.index("if ($DryRun)")
    assert "--dry-run) DRY_RUN=1" in shell
    assert shell.index('log OK "Checksum verified"') < shell.index('if [ "$DRY_RUN" -eq 1 ]')
