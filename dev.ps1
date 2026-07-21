# AI Gator - Dev Server Launcher
# Usage:
#   .\dev.ps1           — primary instance on port 8000
#   .\dev.ps1 -Port 8001 — workbench instance (e.g. for coding agent work)
param(
    [int]$Port = 8000
    # Note: 8001 is reserved for watchdog. Use 8002+ for workbench instances.
    # Example: .\dev.ps1 -Port 8002
)

$basePort = $Port
$projectDir = $PSScriptRoot

Write-Host ""
$instanceLabel = if ($basePort -eq 8000) { "AI Gator Dev Server" } else { "AI Gator Dev Server (workbench :$basePort)" }
Write-Host "=== $instanceLabel ===" -ForegroundColor Cyan

# Stop the built-app tray only when running as the primary instance (port 8000).
# The workbench instance (any other port) leaves the primary alone.
if ($basePort -eq 8000) {
    $tray = Get-Process AIGator -ErrorAction SilentlyContinue
    if ($tray) {
        $tray | ForEach-Object {
            Write-Host "Stopping AIGator tray (PID $($_.Id))..." -ForegroundColor Yellow
            Stop-Process -Id $_.Id -Force
        }
        Start-Sleep -Milliseconds 500
    }
}

# Try to free the preferred port
$port = $basePort
$listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue

if ($listener) {
    $pid_ = $listener.OwningProcess | Sort-Object -Unique | Where-Object { $_ -gt 0 }
    foreach ($id in $pid_) {
        $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "Killing $($proc.ProcessName) (PID $id) on port $port..." -ForegroundColor Yellow
            Stop-Process -Id $id -Force
        }
    }
    Start-Sleep -Milliseconds 1000

    # If port is still stuck (ghost PID), find next free port
    $still = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($still) {
        Write-Host "Port $port held by dead process - finding next free port..." -ForegroundColor Yellow
        for ($p = $basePort + 1; $p -lt $basePort + 10; $p++) {
            $taken = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
            if (-not $taken) { $port = $p; break }
        }
    }
}

# Ensure logs directory exists
$logsDir = Join-Path $projectDir "logs"
if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir | Out-Null }

# Timestamp + rolling log filename (one file per server start, plus a stable "latest" copy)
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logFile   = Join-Path $logsDir "server-$timestamp.log"
$latestLog = Join-Path $logsDir "server.log"

Write-Host ""
Write-Host "Starting dev server on port $port" -ForegroundColor Green
Write-Host "  URL: http://localhost:$port" -ForegroundColor Cyan
Write-Host "  Logs: $logFile" -ForegroundColor Cyan
Write-Host "        $latestLog (stable path for tooling)" -ForegroundColor DarkGray
Write-Host "  Tip: Ctrl+Shift+R in browser after restart" -ForegroundColor Gray
Write-Host ""

Set-Location $projectDir

# The dev server needs the project's dependencies (uvicorn, fastapi, ...) which
# live in .venv. Never fall back to a bare "python": on Windows that resolves to
# the Microsoft Store app-execution-alias stub (which just prints an install
# message and exits) or a system interpreter without our deps - either way the
# server fails confusingly. Require .venv and point at the setup script instead.
$venvPython = Join-Path $projectDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host ""
    Write-Host "No .venv found at:" -ForegroundColor Red
    Write-Host "  $venvPython" -ForegroundColor Red
    Write-Host ""
    Write-Host "Run the setup script first, then re-run dev.ps1:" -ForegroundColor Yellow
    Write-Host "  .\WakeGator.ps1" -ForegroundColor Cyan
    exit 1
}
$python = $venvPython
Write-Host "  Python: $python" -ForegroundColor DarkGray

# Logging: StreamWriter with AutoFlush=true and UTF-8 (no BOM). Why:
#   - python -u disables Python's stdio buffering at the source
#   - AutoFlush=true means every WriteLine hits disk immediately
#   - StreamWriter keeps the file handle open (Add-Content reopens per line and can lag)
#   - UTF-8 without BOM keeps the file friendly to tail/grep/editors
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$logWriter = [System.IO.StreamWriter]::new($logFile, $false, $utf8NoBom)
$logWriter.AutoFlush = $true
$latestWriter = $null
try {
    $latestWriter = [System.IO.StreamWriter]::new($latestLog, $false, $utf8NoBom)
    $latestWriter.AutoFlush = $true
} catch {
    Write-Host "Warning: could not open $latestLog (another dev server may be running) - using timestamped log only" -ForegroundColor Yellow
}

# Watchdog: after "Reloading..." if no "Application startup complete" within this
# many seconds, kill all python processes and restart uvicorn from scratch.
$reloadStuckSeconds = 45

function Write-Log {
    param([string]$msg, [string]$color = "")
    if ($color) { Write-Host $msg -ForegroundColor $color } else { Write-Host $msg }
    $logWriter.WriteLine($msg)
    if ($latestWriter) { $latestWriter.WriteLine($msg) }
}

function Kill-UvicornProcs {
    # Read aider worker PIDs from session JSON files so we never kill a
    # running aider process during a uvicorn hot-reload.
    $workerPids = @()
    $sessionDir = Join-Path $env:USERPROFILE ".gator\sessions"
    if (Test-Path $sessionDir) {
        Get-ChildItem $sessionDir -Filter "*.json" -ErrorAction SilentlyContinue | ForEach-Object {
            try {
                $s = Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json -ErrorAction SilentlyContinue
                if ($s.worker_pid) { $workerPids += [int]$s.worker_pid }
            } catch {}
        }
    }
    Get-Process python* -ErrorAction SilentlyContinue | Where-Object {
        $workerPids -notcontains $_.Id
    } | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
}

# Uvicorn is launched via Start-Process writing stdout+stderr to a temp file.
# The main loop tails that file with a synchronous StreamReader (ReadLine returns
# null immediately when no new data, so the watchdog check runs every 200ms).
# This avoids the ReadLineAsync pitfall where a timed-out task stays in-flight
# and the next ReadLineAsync call throws InvalidOperationException.
$pipePath = Join-Path $env:TEMP "aigator-uvicorn-$port.log"  # port-scoped so two instances don't share
$job = $null

try {
    while ($true) {
        if (Test-Path $pipePath) { Remove-Item $pipePath -Force -ErrorAction SilentlyContinue }

        $uvicornArgs = "/c chcp 65001 > nul && set PYTHONIOENCODING=utf-8 && cd /d `"$projectDir`" && `"$python`" -u -m uvicorn web.app:app --port $port --reload --reload-dir web --reload-include `"*.py`" --timeout-graceful-shutdown 1 > `"$pipePath`" 2>&1"
        $job = Start-Process -FilePath "cmd.exe" -ArgumentList $uvicornArgs -PassThru -WindowStyle Hidden

        # Wait for uvicorn to create the pipe file (up to 3s)
        $waited = 0
        while (-not (Test-Path $pipePath) -and $waited -lt 30) {
            Start-Sleep -Milliseconds 100
            $waited++
        }

        $fs = $null
        $reader = $null
        $openOk = $false
        try {
            $fs = [System.IO.FileStream]::new(
                $pipePath,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read,
                [System.IO.FileShare]::ReadWrite)
            $reader = [System.IO.StreamReader]::new($fs, $utf8NoBom)
            $openOk = $true
        } catch {
            Write-Log "Could not open pipe file - retrying..." "Yellow"
        }

        if (-not $openOk) {
            try { $job.Kill() } catch {}
            Start-Sleep -Milliseconds 500
            continue
        }

        $reloadPending = $false
        $reloadAt = $null
        $restart = $false

        try {
            while (-not $job.HasExited) {
                $line = $reader.ReadLine()
                if ($null -ne $line) {
                    Write-Log $line
                    if ($line -match 'WatchFiles detected changes|Reloading\.\.\.') {
                        $reloadPending = $true
                        $reloadAt = [System.DateTime]::Now
                    }
                    if ($line -match 'Application startup complete|Uvicorn running on') {
                        $reloadPending = $false
                        $reloadAt = $null
                    }
                } else {
                    if ($reloadPending -and ($null -ne $reloadAt) -and
                        ([System.DateTime]::Now - $reloadAt).TotalSeconds -gt $reloadStuckSeconds) {
                        Write-Log "=== Reload stuck for ${reloadStuckSeconds}s - killing and restarting ===" "Yellow"
                        Kill-UvicornProcs
                        try { $job.Kill() } catch {}
                        Start-Sleep -Milliseconds 1500
                        Write-Log "=== Restarting dev server ===" "Cyan"
                        $restart = $true
                        break
                    }
                    Start-Sleep -Milliseconds 200
                }
            }

            if (-not $restart) {
                # Drain any remaining output after normal exit
                while ($true) {
                    $line = $reader.ReadLine()
                    if ($null -eq $line) { break }
                    Write-Log $line
                }
            }
        } finally {
            if ($null -ne $reader) { $reader.Dispose() }
            if ($null -ne $fs) { $fs.Dispose() }
            if (Test-Path $pipePath) { Remove-Item $pipePath -Force -ErrorAction SilentlyContinue }
        }

        if ($restart) { continue }
        break
    }
} finally {
    # Kill the background uvicorn process on any exit including Ctrl+C
    try { if ($null -ne $job) { $job.Kill() } } catch {}
    Kill-UvicornProcs
    $logWriter.Dispose()
    if ($latestWriter) { $latestWriter.Dispose() }
}
