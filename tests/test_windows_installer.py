from pathlib import Path


ROOT = Path(__file__).parent.parent


def test_windows_installer_enumerates_github_release_array():
    powershell = (ROOT / "Get-AIGator.ps1").read_text(encoding="utf-8")

    assert "$releaseResponse = Invoke-RestMethod" in powershell
    assert "$releaseResponse | Where-Object" in powershell
    assert "@(Invoke-RestMethod" not in powershell


def test_windows_installer_accepts_github_asset_digest_without_checksum_file():
    powershell = (ROOT / "Get-AIGator.ps1").read_text(encoding="utf-8")

    assert '$installer.digest -match "^sha256:[A-Fa-f0-9]{64}$"' in powershell
    assert '$expectedHash = ($installer.digest -split ":", 2)[1].ToUpperInvariant()' in powershell
    assert 'if ($checksums.Count -eq 1)' in powershell
