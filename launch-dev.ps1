# AI Gator - Launch the DEV instance (hot-reload backend + Electron shell)
#
# One command to spin up a clean dev environment for testing your changes,
# isolated from the stable app on :8000. It:
#   1. Kills any stale dev backend on the dev port (the #1 cause of
#      "it loaded the old app" - a zombie backend still holding the port).
#   2. Starts the hot-reload backend (dev.ps1) on the dev port.
#   3. Waits until the backend is actually ready.
#   4. Launches the Electron shell attached to it (dev-shell.ps1), always with
#      --remote-debugging-port for the DevTools MCP - unless a shell for this
#      port is already open. An open shell is left alone: it shows
#      "Reconnecting..." while the backend restarts and reloads by itself.
#
#   .\launch-dev.ps1                 - restart the dev backend on :8003 (default);
#                                      open the shell only if none is running
#   .\launch-dev.ps1 -Shell          - also close and relaunch the shell window
#   .\launch-dev.ps1 -Port 8002      - use a different dev port
#   .\launch-dev.ps1 -DebugPort 9223 - use a different remote-debugging port
#
# Runs everything from THIS repo. Edits to web/ hot-reload the backend (reload
# the shell window with Ctrl+R to pick up JS/CSS). Never touches the stable app.
param([int]$Port = 8003, [int]$DebugPort = 9222, [switch]$Shell)

$ErrorActionPreference = "Stop"
$projectDir = $PSScriptRoot

Write-Host ""
Write-Host "=== AI Gator (dev :$Port) ===" -ForegroundColor Cyan

# -- 1. Kill any stale dev backend so we never attach to a zombie ---------------
# A backend left holding the dev port (e.g. an old dev-workbench run, or an
# abruptly-killed uvicorn whose reloader child kept the socket) makes the shell
# load OLD code - the "why is it the classic/old app?" trap. Clear it first.
# Only the LISTENING owner is killed: the shell's own connections to the port
# also show up in netstat, and killing those would close the window.
Write-Host "Clearing any stale dev backend on :$Port ..." -ForegroundColor Yellow
$stalePids = (netstat -ano | Select-String "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING" | ForEach-Object { ($_ -split '\s+')[-1] }) |
    Where-Object { $_ -match '^\d+$' -and $_ -ne '0' } | Sort-Object -Unique
foreach ($id in $stalePids) {
    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($p) {
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
        Write-Host "  killed PID $id ($($p.ProcessName))" -ForegroundColor DarkGray
    } else {
        # PID is already dead but socket handle persists (kernel leak). Ignore.
        Write-Host "  PID $id already gone (socket will clear)" -ForegroundColor DarkGray
    }
}
# The shell for THIS port is identified by its userData profile tag
# "gator-shell-<port>" in the process command line (see shell/main.js
# app.setPath). Matching on it never touches the stable app (:8000) or another
# dev instance. It is closed only with -Shell; otherwise it stays open and
# reconnects on its own when the backend is back.
$profileTag = "gator-shell-$Port"
$shellProcs = @(Get-CimInstance Win32_Process -Filter "Name='electron.exe' OR Name='AI Gator.exe'" -OperationTimeoutSec 10 -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match [regex]::Escape($profileTag) })
$launchShell = $Shell -or ($shellProcs.Count -eq 0)
Start-Sleep -Seconds 2

# If the port is stuck in a "zombie" LISTEN with a dead owning PID, this is
# often NOT actually a zombie: uvicorn --reload's parent process binds the
# socket, then worker subprocesses inherit the handle across reloads. Windows'
# TCP table keeps reporting the ORIGINAL binding PID even after it exits and a
# child takes over -- netstat/Get-NetTCPConnection never update the owner.
# So a "dead PID + LISTENING" reading can mean a perfectly healthy live server.
# Always check the actual HTTP health endpoint FIRST before assuming zombie.
$stillListening = netstat -ano | Select-String ":$Port\s+.*LISTENING"
if ($stillListening) {
    try {
        $probe = Invoke-WebRequest -Uri "http://localhost:$Port/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($probe.StatusCode -eq 200) {
            Write-Host "Port $Port shows a stale owning PID but is actually serving a healthy Gator backend." -ForegroundColor Green
            Write-Host "Skipping restart -- using the existing backend." -ForegroundColor Cyan
            if ($launchShell) {
                & (Join-Path $projectDir "dev-shell.ps1") -Port $Port -DebugPort $DebugPort -Restart
            }
            Write-Host ""
            Write-Host "Dev instance is up on :$Port." -ForegroundColor Green
            exit 0
        }
    } catch {
        # Not responding -- fall through to the real zombie-recovery path below.
    }
    Write-Host "Port $Port has a zombie socket -- attempting force-release..." -ForegroundColor Yellow
    $venvPy = Join-Path $projectDir ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) {
        # Write Python to a temp file -- avoids PowerShell misinterpreting
        # commas and parentheses inside an inline -c string.
        $tmpPy = Join-Path $env:TEMP "gator-release-port.py"
        $pyCode = @"
import socket, sys
port = int(sys.argv[1])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(('127.0.0.1', port))
    s.close()
    print('released')
except Exception as e:
    s.close()
    print('failed:', e)
"@
        Set-Content -Path $tmpPy -Value $pyCode -Encoding UTF8
        & $venvPy $tmpPy $Port 2>$null | Out-Null
        Remove-Item $tmpPy -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
    $stillListening = netstat -ano | Select-String ":$Port\s+.*LISTENING"
    if ($stillListening) {
        Write-Host "Force-release did not work -- waiting for OS to free the socket (up to 60s)..." -ForegroundColor Yellow
        $waited = 0
        while ($waited -lt 60) {
            Start-Sleep -Seconds 3
            $waited += 3
            $stillListening = netstat -ano | Select-String ":$Port\s+.*LISTENING"
            if (-not $stillListening) { break }
            Write-Host "  still waiting... ($waited s)" -ForegroundColor DarkGray
        }
        if ($stillListening) {
            Write-Host "Port $Port is still held after 60s. Run on a different port:" -ForegroundColor Red
            Write-Host "  .\launch-dev.ps1 -Port $($Port + 1)" -ForegroundColor Yellow
            exit 1
        }
    }
    Write-Host "Port $Port released." -ForegroundColor Green
}

# -- 2. Start the hot-reload backend in a new window --------------------------
Write-Host "Starting dev backend on :$Port ..." -ForegroundColor Cyan
$backend = Start-Process -FilePath "powershell.exe" `
    -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $projectDir "dev.ps1"), "-Port", "$Port" `
    -WorkingDirectory $projectDir -PassThru

# -- 3. Wait for the backend to be ready --------------------------------------
Write-Host "Waiting for the backend to come up ..." -ForegroundColor DarkGray
$ready = $false
$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    try {
        Invoke-WebRequest -Uri "http://localhost:$Port/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop | Out-Null
        $ready = $true; break
    } catch { Start-Sleep -Milliseconds 500 }
}
if (-not $ready) {
    Write-Host "Backend didn't become ready in time - check the dev.ps1 window for errors." -ForegroundColor Red
    exit 1
}
Write-Host "Backend ready." -ForegroundColor Green

# -- 4. Launch the Electron shell attached to the dev backend -----------------
if ($launchShell) {
    Write-Host "Launching the Electron shell (attached to :$Port, MCP on :$DebugPort) ..." -ForegroundColor Cyan
    & (Join-Path $projectDir "dev-shell.ps1") -Port $Port -DebugPort $DebugPort -Restart
} else {
    Write-Host "Shell for :$Port is already open - leaving it running; it reconnects on its own." -ForegroundColor Cyan
}

Write-Host ""
Write-Host "Dev instance is up on :$Port. The stable app (:8000) is untouched." -ForegroundColor Green
Write-Host "  - Edit web/  -> backend hot-reloads; press Ctrl+R in the shell to refresh." -ForegroundColor DarkGray
Write-Host "  - Close the dev.ps1 window to stop the dev backend." -ForegroundColor DarkGray
Write-Host ""
