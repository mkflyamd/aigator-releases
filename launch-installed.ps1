# AI Gator - Launch the STABLE app (the "installed app" equivalent)
#
# Runs the app exactly the way a real install does: via the tray, which starts
# the backend (watchdog + uvicorn on :8000) and then launches the Electron shell
# with the correct shell/ path. Use this as your everyday "open AI Gator".
#
#   .\launch-installed.ps1          - start the stable app
#   .\launch-installed.ps1 -Restart - kill any running instance first, then start
#
# WHY A SCRIPT, NOT A START-MENU SHORTCUT: Windows keeps re-pinning the "AI Gator"
# shortcut to the bare electron exe (AI Gator.exe with no shell path), which just
# shows Electron's "run a local app" splash. Launching through the tray here is
# corruption-proof - the tray always passes the shell/ path and GATOR_URL.
param([switch]$Restart)

$ErrorActionPreference = "Stop"
$projectDir = $PSScriptRoot
$venvPyw    = Join-Path $projectDir ".venv\Scripts\pythonw.exe"
$trayScript = Join-Path $projectDir "tray\aigator_tray.py"

Write-Host ""
Write-Host "=== AI Gator (stable) ===" -ForegroundColor Green

if (-not (Test-Path $venvPyw)) {
    Write-Host "No .venv found. Run .\WakeGator.ps1 first." -ForegroundColor Red
    exit 1
}

# The tray's own single-instance lock + identity sweep normally handle dedup, but
# -Restart forces a clean restart of the STABLE instance only (its Electron is
# tagged "gator-shell-8000"; its backend is the tray/watchdog/uvicorn on :8000).
# Scoped so it does NOT kill a dev instance you may have running on another port.
if ($Restart) {
    Write-Host "Stopping the stable AI Gator (:8000)..." -ForegroundColor Yellow
    # Electron: only the :8000 profile (leave dev instances alone).
    Get-CimInstance Win32_Process -Filter "Name='electron.exe' OR Name='AI Gator.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'gator-shell-8000' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    # Backend: the tray, plus watchdog/uvicorn bound to :8000 (dev backends run on
    # other ports, so match the port to avoid killing them).
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'aigator_tray' -or $_.CommandLine -match 'watchdog\.py' -or $_.CommandLine -match 'port 8000\b' -or $_.CommandLine -match 'web\.app:app.*8000' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}

Write-Host "Starting via the tray (backend :8000 + Electron shell)..." -ForegroundColor Cyan
Start-Process -FilePath $venvPyw -ArgumentList "`"$trayScript`"" -WorkingDirectory $projectDir -WindowStyle Hidden

Write-Host "AI Gator is starting. Look for the tray icon; the app window opens shortly." -ForegroundColor Green
Write-Host ""
