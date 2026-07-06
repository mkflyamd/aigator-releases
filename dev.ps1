# AI Gator - Dev Server Launcher

$basePort = 8000
$projectDir = $PSScriptRoot

Write-Host ""
Write-Host "=== AI Gator Dev Server ===" -ForegroundColor Cyan

# Stop the built-app tray first. It relaunches its own backend from AppData on
# port 8000 and would re-shadow this dev server (serving stale static).
$tray = Get-Process AIGator -ErrorAction SilentlyContinue
if ($tray) {
    $tray | ForEach-Object {
        Write-Host "Stopping AIGator tray (PID $($_.Id))..." -ForegroundColor Yellow
        Stop-Process -Id $_.Id -Force
    }
    Start-Sleep -Milliseconds 500
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

# cmd merges 2>&1 before bytes reach PowerShell, so uvicorn's stderr INFO logs
# don't get wrapped in red NativeCommandError blocks. Ctrl+C still propagates.
#
# Logging: StreamWriter with AutoFlush=true and UTF-8 (no BOM). Why:
#   - python -u disables Python's stdio buffering at the source
#   - AutoFlush=true means every WriteLine hits disk immediately, so `tail -f`
#     and editor "follow" never show stale data
#   - StreamWriter keeps the file handle open (Add-Content reopens per line and
#     can lag under load)
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
try {
    # --timeout-graceful-shutdown: the app serves a long-lived SSE stream
    # (/api/notifications/stream) the browser keeps open via EventSource. On a
    # --reload restart, uvicorn's graceful shutdown would otherwise block forever
    # waiting for that connection to drain, so the reload appears to "hang". Cap
    # the wait at 2s so edits reliably restart the server.
    # --reload-include: only watch Python files — avoids spurious reloads triggered
    # by runtime writes to .json/.md/.html inside web/ (skill manifests, caches, etc.)
    cmd /c "chcp 65001 > nul && set PYTHONIOENCODING=utf-8 && cd /d `"$projectDir`" && `"$python`" -u -m uvicorn web.app:app --port $port --reload --reload-dir web --reload-include `"*.py`" --timeout-graceful-shutdown 1 2>&1" |
        ForEach-Object {
            Write-Host $_
            $logWriter.WriteLine($_)
            if ($latestWriter) { $latestWriter.WriteLine($_) }
        }
} finally {
    $logWriter.Dispose()
    if ($latestWriter) { $latestWriter.Dispose() }
}
