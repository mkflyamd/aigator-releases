# AI Gator - Dev Server Launcher

$basePort = 8000
$projectDir = $PSScriptRoot

Write-Host ""
Write-Host "=== AI Gator Dev Server ===" -ForegroundColor Cyan

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

$venvPython = Join-Path $projectDir ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }
if ($python -ne "python") {
    Write-Host "  Python: $python" -ForegroundColor DarkGray
}

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
    cmd /c "chcp 65001 > nul && set PYTHONIOENCODING=utf-8 && `"$python`" -u -m uvicorn web.app:app --port $port --reload --reload-dir web 2>&1" |
        ForEach-Object {
            Write-Host $_
            $logWriter.WriteLine($_)
            if ($latestWriter) { $latestWriter.WriteLine($_) }
        }
} finally {
    $logWriter.Dispose()
    if ($latestWriter) { $latestWriter.Dispose() }
}
