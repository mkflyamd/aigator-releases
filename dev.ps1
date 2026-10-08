# AI Gator - Dev Server Launcher
# Usage:
#   .\dev.ps1           — primary instance on port 8000
#   .\dev.ps1 -Port 8002 — workbench instance (e.g. for coding agent work)
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

# Decode a process exit code into a plain-English cause.
# Why this exists: when uvicorn dies unexpectedly the server log just stops
# mid-line -- no traceback, no shutdown notice, nothing saying WHY. The exit
# code is the one signal that separates causes which are otherwise identical
# from the log alone (native crash vs. external kill vs. Ctrl+C vs. clean exit).
# Diagnostic only: nothing here changes how the server runs.
#
# Codes are matched as hex STRINGS on purpose. In PowerShell 5.1 the literal
# 0xFFFFFFFF is Int32 -1 (not 4294967295), so a switch on hex literals would
# misclassify externally-killed processes. Formatting to a string first avoids
# every signed/unsigned ambiguity.
function Get-ExitReason {
    param($code)
    if ($null -eq $code) { return "unknown - exit code unavailable" }
    $hex = '0x{0:X8}' -f ([uint32]($code -band 0xFFFFFFFFL))
    switch ($hex) {
        '0x00000000' { return "clean exit - the process was asked to stop (or stopped itself) without error" }
        '0x00000001' { return "generic failure - typically taskkill /F, or an unhandled error during startup" }
        '0xFFFFFFFF' { return "KILLED EXTERNALLY - TerminateProcess from Stop-Process, Task Manager, or an EDR/AV agent" }
        '0xC000013A' { return "Ctrl+C, or the console window was closed" }
        '0xC0000005' { return "NATIVE CRASH - access violation: a C extension faulted (e.g. the PTY/ConPTY layer, SSL, sqlite)" }
        '0xC00000FD' { return "NATIVE CRASH - stack overflow" }
        '0xC0000409' { return "NATIVE CRASH - stack buffer overrun / fail-fast" }
        '0xC0000017' { return "out of memory" }
        default      { return "unrecognised code $hex - look it up as an NTSTATUS value" }
    }
}

# Should an unexpected exit bring the server back up?
#
# A dev backend killed out from under you -- an agent sweeping `Get-Process
# python`, an EDR, a stray Stop-Process -- otherwise leaves a dead terminal, a
# silent window, and no running server until you notice. Restart those. Do NOT
# restart when the exit was deliberate (Ctrl+C, console closed, clean exit),
# because that's you asking it to stop.
function Should-AutoRestart {
    param($code)
    if ($null -eq $code) { return $false }
    $hex = '0x{0:X8}' -f ([uint32]($code -band 0xFFFFFFFFL))
    switch ($hex) {
        '0x00000000' { return $false }  # clean exit - something asked it to stop
        '0xC000013A' { return $false }  # Ctrl+C / console closed - user intent
        default      { return $true }   # killed, crashed, or failed to start
    }
}

# Collect every descendant PID of $RootPid (children, grandchildren, ...).
# One CIM snapshot, then walk it in memory -- the process tree is the only
# proof of ownership that cannot be spoofed by a port number or a name match.
function Get-DescendantPids {
    param([int]$RootPid)
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Select-Object ProcessId, ParentProcessId)
    $found = @()
    $frontier = @($RootPid)
    while ($frontier.Count -gt 0) {
        $next = @()
        foreach ($f in $frontier) {
            foreach ($p in $all) {
                if ($p.ParentProcessId -eq $f -and $p.ProcessId -ne $RootPid -and $found -notcontains $p.ProcessId) {
                    $found += $p.ProcessId
                    $next += $p.ProcessId
                }
            }
        }
        $frontier = $next
    }
    return $found
}

function Kill-UvicornProcs {
    # Kill ONLY the uvicorn processes THIS dev.ps1 instance started.
    #
    # It used to select targets purely by "who is listening on $port", with no
    # check that those processes belonged to this instance -- and it runs from
    # the finally block on EVERY exit (normal end, Ctrl+C, window closed). With
    # two dev.ps1 windows on the same port, closing the older one would kill the
    # newer one's perfectly healthy backend. That looks exactly like the bug we
    # are chasing: the server vanishes mid-session with no traceback and no
    # crash event, and HTTP ("Failed to fetch") plus the xterm WebSocket drop in
    # the same instant because the whole process is gone.
    #
    # Ownership now comes from two independent sources, both instance-scoped:
    #   1. uvicorn prints its own PIDs ("Started reloader process [N]" /
    #      "Started server process [N]"); we capture them as they stream past.
    #   2. the live descendant tree of the .cmd wrapper we launched ($job).
    # Source 2 also covers a startup that died before uvicorn printed anything.
    #
    # Nothing outside that set is ever touched, so this can no longer reach
    # another instance's server.
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

    # (2) live descendants of our own launcher -- provably ours right now, so
    # they need no further guard.
    $treePids = @()
    if ($null -ne $job) {
        try { $treePids = @(Get-DescendantPids -RootPid $job.Id) } catch {}
        $treePids += $job.Id
    }

    # (1) PIDs uvicorn reported. These may be stale by now, so guard against PID
    # reuse before killing: the process must still look like one of ours.
    $logPids = @()
    foreach ($id in @($script:ownedPids)) {
        if ($treePids -contains $id) { continue }
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
        if ($null -eq $p) { continue }
        if ($p.Name -notmatch '^python') { continue }
        if ($p.CommandLine -notmatch "uvicorn") { continue }
        if ($p.CommandLine -notmatch "--port\s+$port\b") { continue }
        $logPids += $id
    }

    $targets = @($treePids + $logPids) | Sort-Object -Unique |
        Where-Object { $_ -gt 0 -and $workerPids -notcontains $_ }

    foreach ($id in $targets) {
        $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "  Stopping $($proc.Name) (PID $id) [this instance]" -ForegroundColor DarkGray
            Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
        }
    }

    # If the socket is still held after killing everything we own, it belongs to
    # someone else (another dev.ps1) or it is a kernel handle leak from a dead
    # PID. Either way it is NOT ours to kill -- just report it. Startup-time
    # port clearing is handled separately, before this instance owns anything.
    $stillHeld = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess | Sort-Object -Unique | Where-Object { $_ -gt 0 })
    foreach ($id in $stillHeld) {
        if ($targets -contains $id) { continue }
        Write-Host "  Port $port still held by PID $id - not ours, leaving it alone" -ForegroundColor DarkGray
    }
}

# Uvicorn is launched via Start-Process writing stdout+stderr to a temp file.
# The main loop tails that file with a synchronous StreamReader (ReadLine returns
# null immediately when no new data, so the watchdog check runs every 200ms).
# This avoids the ReadLineAsync pitfall where a timed-out task stays in-flight
# and the next ReadLineAsync call throws InvalidOperationException.
$pipePath = Join-Path $env:TEMP "aigator-uvicorn-$port.log"  # port-scoped so two instances don't share
$job = $null
# PIDs uvicorn reports for its own processes. This is how Kill-UvicornProcs
# knows which server is ours and which belongs to another dev.ps1 instance.
$script:ownedPids = @()

# Auto-restart budget. Bounded so a genuine startup failure (bad import, port
# permanently taken) can't turn into an endless restart storm that buries the
# real error in log noise.
$autoRestartMax = 5
$autoRestartWindowMin = 10
$restartStamps = @()

try {
    while ($true) {
        if (Test-Path $pipePath) { Remove-Item $pipePath -Force -ErrorAction SilentlyContinue }; if (Test-Path "$pipePath.out") { Remove-Item "$pipePath.out" -Force -ErrorAction SilentlyContinue }; if (Test-Path "$pipePath.err") { Remove-Item "$pipePath.err" -Force -ErrorAction SilentlyContinue }

        # --reload-exclude: keep WatchFiles off churny/irrelevant paths. Without
        # these the watcher recurses the whole web/ tree (incl. __pycache__,
        # caches, node_modules, test artifacts, generated logs) and can peg CPU
        # / get stuck mid-reload, which manifests as the backend hanging (the
        # dev server "crash" we kept hitting). Only *.py under web/ triggers a
        # reload; everything below is ignored.
        #
        # PATTERN STYLE MATTERS: path-style globs like "*/node_modules/*" get
        # glob-EXPANDED into real directory lists by Python/Click on Windows
        # (before uvicorn's WatchFiles ever sees them), which uvicorn then rejects
        # as "Got unexpected extra arguments" — the crash you hit once node_modules
        # /__pycache__ existed. No launcher trick fixes it (Start-Process, cmd /c,
        # .cmd wrapper, & $py @array all expand it). The fix is the PATTERN:
        # surrounding-wildcard forms like "*node_modules*" / "*__pycache__*" are
        # NOT expanded and match the same paths for exclusion purposes. Keep the
        # cmd wrapper only for UTF-8 + output redirect (it doesn't cause/​fix the
        # expansion; the patterns do).
        $cmdFile = Join-Path $env:TEMP "aigator-uvicorn-$port.cmd"
        $cmdBody = @"
@echo off
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
cd /d "$projectDir"
"$python" -u -m uvicorn web.app:app --port $port --reload --reload-dir web --reload-include "*.py" --reload-exclude "*.log" --reload-exclude "*.tmp" --reload-exclude "*__pycache__*" --reload-exclude "*.pyc" --reload-exclude "*node_modules*" --reload-exclude "*.pytest_cache*" --reload-exclude "*outputs*" --reload-exclude "*work*" --timeout-graceful-shutdown 0 > "$pipePath" 2>&1
"@
        Set-Content -Path $cmdFile -Value $cmdBody -Encoding ASCII
        $job = Start-Process -FilePath $cmdFile -PassThru -WindowStyle Hidden
        $startedAt = Get-Date
        # New server -- forget the previous run's PIDs so a restart can never
        # carry stale ownership forward onto a recycled PID.
        $script:ownedPids = @()

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
                    # uvicorn announces its own PIDs on startup and after every
                    # reload ("Started reloader process [N]" / "Started server
                    # process [N]"). Taking them straight from its output is
                    # exact -- no port lookup, no name matching, no guessing.
                    if ($line -match 'Started (?:reloader|server) process \[(\d+)\]') {
                        $seen = [int]$Matches[1]
                        if ($script:ownedPids -notcontains $seen) { $script:ownedPids += $seen }
                    }
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

                # Record HOW uvicorn exited. Previously this path was completely
                # silent, so an unexpected death was indistinguishable from the
                # log simply stopping -- there was nothing to diagnose from.
                $exitCode = $null
                try { $exitCode = $job.ExitCode } catch {}
                $ranFor = [int]((Get-Date) - $startedAt).TotalSeconds
                Write-Log ""
                Write-Log "=== uvicorn exited after ${ranFor}s ===" "Yellow"
                Write-Log "    exit code : $exitCode" "Yellow"
                Write-Log "    meaning   : $(Get-ExitReason $exitCode)" "Yellow"

                # Are any uvicorn python processes still alive? This separates
                # "python itself died" from "the .cmd wrapper died and left
                # python orphaned" -- two very different failure modes that look
                # identical from the exit code alone.
                #
                # Match on the uvicorn arguments, NOT on the .cmd wrapper name:
                # the wrapper applies "> file 2>&1" via cmd.exe, so the redirect
                # and the wrapper path never appear in python's own command line.
                # Only the cmd.exe shell carries "aigator-uvicorn-<port>", so
                # matching python against that name silently finds nothing and
                # would always report a misleading "none".
                $survivors = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                    Where-Object { $_.Name -match '^python' -and $_.CommandLine -match "uvicorn.*--port\s+$port\b" })
                if ($survivors.Count -gt 0) {
                    Write-Log "    orphaned  : $($survivors.Count) python process(es) STILL ALIVE: $(($survivors | ForEach-Object { $_.ProcessId }) -join ', ')" "Yellow"
                } else {
                    Write-Log "    orphaned  : none - every uvicorn python process is gone" "Yellow"
                }
                Write-Log "=======================================" "Yellow"

                # Also append to a persistent history. The per-start server logs
                # rotate, so without this the evidence for an intermittent death
                # is scattered across dozens of files.
                try {
                    $exitLine = "{0}  port={1}  ran={2}s  code={3}  orphaned={4}  {5}" -f `
                        (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $port, $ranFor, $exitCode,
                        $survivors.Count, (Get-ExitReason $exitCode)
                    Add-Content -Path (Join-Path $logsDir "server-exits.log") -Value $exitLine -Encoding UTF8
                } catch {}

                # Bring it back if the exit wasn't something you asked for.
                if (Should-AutoRestart $exitCode) {
                    $now = Get-Date
                    $restartStamps = @($restartStamps |
                        Where-Object { ($now - $_).TotalMinutes -lt $autoRestartWindowMin })
                    if ($restartStamps.Count -ge $autoRestartMax) {
                        Write-Log "=== $autoRestartMax restarts in $autoRestartWindowMin min - giving up ===" "Red"
                        Write-Log "    Something is killing this server repeatedly, or it can't start." "Red"
                        Write-Log "    See logs\server-exits.log for the cause of each exit." "Red"
                    } else {
                        $restartStamps += $now
                        # Clear out anything of ours still holding the port before
                        # rebinding (ownership-scoped, so other instances are safe).
                        Kill-UvicornProcs
                        Write-Log "=== auto-restarting ($($restartStamps.Count)/$autoRestartMax within ${autoRestartWindowMin}m) ===" "Cyan"
                        Start-Sleep -Milliseconds 1000
                        $restart = $true
                    }
                }
            }
        } finally {
            if ($null -ne $reader) { $reader.Dispose() }
            if ($null -ne $fs) { $fs.Dispose() }
            if (Test-Path $pipePath) { Remove-Item $pipePath -Force -ErrorAction SilentlyContinue }; if (Test-Path "$pipePath.out") { Remove-Item "$pipePath.out" -Force -ErrorAction SilentlyContinue }; if (Test-Path "$pipePath.err") { Remove-Item "$pipePath.err" -Force -ErrorAction SilentlyContinue }
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
