# +==========================================================================+
# |  Get-AIGator - one-line bootstrap for AI Gator (source / pip track)        |
# |  Downloads the latest source, extracts it, and runs WakeGator.             |
# |                                                                            |
# |  Paste-and-go:                                                             |
# |    irm https://mkflyamd.github.io/aigator-releases/install.ps1 | iex       |
# |                                                                            |
# |  Or download this file and run it:                                         |
# |    powershell -NoProfile -ExecutionPolicy Bypass -File Get-AIGator.ps1     |
# +==========================================================================+

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # faster Invoke-WebRequest
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo   = "mkflyamd/aigator-releases"
$ZipUrl = "https://github.com/$Repo/archive/refs/heads/main.zip"
$Dest   = Join-Path $env:LOCALAPPDATA "Programs\AIGator"

function Info { param([string]$t) Write-Host "      -> $t" -ForegroundColor DarkGray }
function Ok   { param([string]$t) Write-Host "      " -NoNewline; Write-Host "OK " -ForegroundColor Green -NoNewline; Write-Host $t -ForegroundColor Gray }
function Fail { param([string]$t) Write-Host "      x $t" -ForegroundColor Red }

Write-Host ""
Write-Host "  AI Gator - fetching the latest version..." -ForegroundColor Green
Write-Host ""

$tmpZip = Join-Path $env:TEMP ("aigator-" + [Guid]::NewGuid().ToString("N") + ".zip")
$tmpEx  = Join-Path $env:TEMP ("aigator-ex-" + [Guid]::NewGuid().ToString("N"))

try {
    Info "Downloading source ..."
    Invoke-WebRequest -Uri $ZipUrl -OutFile $tmpZip -UseBasicParsing
    Ok "Downloaded."

    Info "Extracting ..."
    Expand-Archive -Path $tmpZip -DestinationPath $tmpEx -Force
    $inner = Get-ChildItem -Path $tmpEx -Directory | Select-Object -First 1
    if (-not $inner) { throw "Unexpected archive layout - no top-level folder found." }

    # Copy source into place, overwriting files but leaving an existing .venv
    # intact so re-runs (updates) skip the slow full reinstall.
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
    Copy-Item -Path (Join-Path $inner.FullName "*") -Destination $Dest -Recurse -Force
    Ok "Installed to $Dest"
}
catch {
    Fail "Could not download AI Gator: $($_.Exception.Message)"
    Fail "If you're on a corporate network, a proxy may be blocking the download."
    Read-Host "      Press Enter to exit"
    exit 1
}
finally {
    Remove-Item $tmpZip -Force -ErrorAction SilentlyContinue
    Remove-Item $tmpEx -Recurse -Force -ErrorAction SilentlyContinue
}

$wake = Join-Path $Dest "WakeGator.ps1"
if (-not (Test-Path $wake)) {
    Fail "Setup script not found at $wake"
    Read-Host "      Press Enter to exit"
    exit 1
}
Unblock-File $wake -ErrorAction SilentlyContinue

Write-Host ""
Info "Handing off to setup ..."
Write-Host ""
& $wake
