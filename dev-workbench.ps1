# AI Gator - Workbench Dev Server
#
# Runs a second Gator instance on port 8002 against an isolated git worktree
# so the coding agent can freely edit files without touching the primary
# instance on port 8000.
#
# Usage:
#   .\dev-workbench.ps1          - start (creates worktree if needed)
#   .\dev-workbench.ps1 -Teardown - stop workbench + delete the worktree branch
#   .\dev-workbench.ps1 -Stop    - stop workbench process only (keep worktree)
#
# Workflow:
#   1. Run this script - starts the workbench backend on :8002 against an
#      isolated worktree (sibling folder "<primary>-agent-work").
#   2. Open it in the Electron shell (separate terminal): .\dev-shell.ps1
#      (defaults to :8002). In the Code tab, select the worktree project and let
#      the coding agent edit files freely. Your primary checkout is unaffected.
#   3. When happy with the changes, merge them from your primary checkout:
#        git merge agent-work
#   4. To discard everything and clean up:
#        .\dev-workbench.ps1 -Teardown

param(
    [switch]$Teardown,
    [switch]$Stop
)

$WorkbenchPort  = 8002
$WorktreeBranch = "agent-work"
$PrimaryDir     = $PSScriptRoot
# The worktree MUST live at a path distinct from the primary checkout — git
# refuses to add a worktree at the main working tree's own path. Derive a
# sibling folder from the primary's actual name + branch (e.g.
# "AgenticPOC-dev" -> "AgenticPOC-dev-agent-work") so it can never collide,
# regardless of what the primary folder is named. (The old code hardcoded
# "AgenticPOC-dev", which resolved to the primary itself when the repo folder
# was named that — breaking `git worktree add`.)
$PrimaryName    = Split-Path $PrimaryDir -Leaf
$WorktreeDir    = Join-Path (Split-Path $PrimaryDir -Parent) "$PrimaryName-$WorktreeBranch"
$VenvPython     = Join-Path $PrimaryDir ".venv\Scripts\python.exe"
$PipePath       = Join-Path $env:TEMP "aigator-uvicorn-$WorkbenchPort.log"
$utf8NoBom      = [System.Text.UTF8Encoding]::new($false)

# -- Helpers -------------------------------------------------------------------

function Get-WorkbenchPid {
    $conn = Get-NetTCPConnection -LocalPort $WorkbenchPort -State Listen -ErrorAction SilentlyContinue
    if ($conn) { return ($conn.OwningProcess | Sort-Object -Unique | Where-Object { $_ -gt 0 }) }
    return @()
}

function Stop-Workbench {
    $pids = Get-WorkbenchPid
    if ($pids) {
        foreach ($id in $pids) {
            $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host "Stopping $($proc.ProcessName) (PID $id) on port $WorkbenchPort..." -ForegroundColor Yellow
                Stop-Process -Id $id -Force
            }
        }
        Write-Host "Workbench stopped." -ForegroundColor Green
    } else {
        Write-Host "No workbench process running on port $WorkbenchPort." -ForegroundColor Gray
    }
}

function Remove-Worktree {
    if (Test-Path $WorktreeDir) {
        Write-Host "Removing worktree at $WorktreeDir..." -ForegroundColor Yellow
        Push-Location $PrimaryDir
        git worktree remove --force $WorktreeDir 2>&1 | Out-Null
        # Delete the branch too if it exists and is fully merged
        $branchExists = git branch --list $WorktreeBranch
        if ($branchExists) {
            git branch -D $WorktreeBranch 2>&1 | Out-Null
            Write-Host "Deleted branch '$WorktreeBranch'." -ForegroundColor Green
        }
        Pop-Location
        Write-Host "Worktree removed." -ForegroundColor Green
    } else {
        Write-Host "No worktree found at $WorktreeDir." -ForegroundColor Gray
    }
}

# -- -Stop: just kill the process ---------------------------------------------

if ($Stop) {
    Stop-Workbench
    exit 0
}

# -- -Teardown: kill process + remove worktree ---------------------------------

if ($Teardown) {
    Stop-Workbench
    Remove-Worktree
    Write-Host ""
    Write-Host "Teardown complete. Primary Gator on :8000 is unaffected." -ForegroundColor Cyan
    exit 0
}

# -- Start ---------------------------------------------------------------------

Write-Host ""
Write-Host "=== AI Gator Workbench (:$WorkbenchPort) ===" -ForegroundColor Cyan
Write-Host "  Primary  : http://localhost:8000  (your normal Gator - untouched)" -ForegroundColor DarkGray
Write-Host "  Workbench: http://localhost:$WorkbenchPort  (coding agent edits here)" -ForegroundColor Green
Write-Host ""

# Check venv exists
if (-not (Test-Path $VenvPython)) {
    Write-Host "No .venv found at $VenvPython" -ForegroundColor Red
    Write-Host "Run .\WakeGator.ps1 first to set up the environment." -ForegroundColor Yellow
    exit 1
}

# Check nothing already on port 8002
$existing = Get-WorkbenchPid
if ($existing) {
    Write-Host "Something is already running on port $WorkbenchPort (PID $existing)." -ForegroundColor Yellow
    Write-Host "Run '.\dev-workbench.ps1 -Stop' first, or open http://localhost:$WorkbenchPort" -ForegroundColor Yellow
    exit 1
}

# Create worktree if it doesn't exist
if (-not (Test-Path $WorktreeDir)) {
    Write-Host "Creating worktree on branch '$WorktreeBranch'..." -ForegroundColor Cyan
    Push-Location $PrimaryDir

    # If branch already exists (leftover), reuse it; otherwise create fresh from HEAD
    $branchExists = git branch --list $WorktreeBranch
    # Redirect stderr to null so PS5's NativeCommandError doesn't fire on
    # git's informational progress messages (Preparing worktree, Updating files)
    if ($branchExists) {
        git worktree add $WorktreeDir $WorktreeBranch 2>$null
    } else {
        git worktree add -b $WorktreeBranch $WorktreeDir HEAD 2>$null
    }
    Pop-Location

    if (-not (Test-Path $WorktreeDir)) {
        Write-Host "Failed to create worktree." -ForegroundColor Red
        exit 1
    }
    Write-Host "Worktree created at $WorktreeDir" -ForegroundColor Green
} else {
    Write-Host "Reusing existing worktree at $WorktreeDir" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "  Worktree : $WorktreeDir" -ForegroundColor DarkGray
Write-Host "  Branch   : $WorktreeBranch" -ForegroundColor DarkGray
Write-Host "  Python   : $VenvPython" -ForegroundColor DarkGray
Write-Host ""
$WorktreeName = Split-Path $WorktreeDir -Leaf
Write-Host "HOW TO USE:" -ForegroundColor Cyan
Write-Host "  1. Open the workbench in the Electron shell (separate terminal):" -ForegroundColor White
Write-Host "       .\dev-shell.ps1            (attaches to this workbench on :$WorkbenchPort)" -ForegroundColor Cyan
Write-Host "  2. Go to the Code tab. Click the project pill and select:" -ForegroundColor White
Write-Host "       $WorktreeName  <-- the worktree, NOT your primary checkout" -ForegroundColor Yellow
Write-Host "     If it is not listed yet, click '+Add app' and add this path:" -ForegroundColor DarkGray
Write-Host "       $WorktreeDir" -ForegroundColor Yellow
Write-Host "     The agent edits the worktree - your primary checkout is NEVER touched." -ForegroundColor DarkGray
Write-Host "  3. Ask the coding agent to make changes as normal." -ForegroundColor White
Write-Host "  4. When happy, merge into the primary (from your primary checkout):" -ForegroundColor White
Write-Host "       git merge $WorktreeBranch" -ForegroundColor Cyan
Write-Host "     Then reload the shell window (Ctrl+R) to pick up the changes." -ForegroundColor DarkGray
Write-Host "  5. If the agent made a mess, discard without affecting :8000:" -ForegroundColor White
Write-Host "       .\dev-workbench.ps1 -Teardown" -ForegroundColor Cyan
Write-Host ""
Write-Host "OPTIONAL: http://localhost:8002 lets you visually preview changes" -ForegroundColor DarkGray
Write-Host "  in a live Gator instance before merging. Not required." -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Ctrl+C to stop the workbench server." -ForegroundColor Gray
Write-Host "  To merge agent changes into primary:" -ForegroundColor Gray
Write-Host "    git merge $WorktreeBranch" -ForegroundColor Cyan
Write-Host "  To discard everything:" -ForegroundColor Gray
Write-Host "    .\dev-workbench.ps1 -Teardown" -ForegroundColor Cyan
Write-Host ""

# Launch uvicorn against the worktree directory
if (Test-Path $PipePath) { Remove-Item $PipePath -Force -ErrorAction SilentlyContinue }

$uvicornArgs = "/c chcp 65001 > nul && set PYTHONIOENCODING=utf-8 && cd /d `"$WorktreeDir`" && `"$VenvPython`" -u -m uvicorn web.app:app --port $WorkbenchPort --reload --reload-dir web --reload-include `"*.py`" --reload-delay 2 --timeout-graceful-shutdown 30 > `"$PipePath`" 2>&1"
$job = Start-Process -FilePath "cmd.exe" -ArgumentList $uvicornArgs -PassThru -WindowStyle Hidden

# Wait for pipe file
$waited = 0
while (-not (Test-Path $PipePath) -and $waited -lt 30) {
    Start-Sleep -Milliseconds 100
    $waited++
}

# Tail the log, forwarding to console
$fs = $null; $reader = $null
try {
    $fs = [System.IO.FileStream]::new(
        $PipePath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::ReadWrite)
    $reader = [System.IO.StreamReader]::new($fs, $utf8NoBom)

    while (-not $job.HasExited) {
        try {
            $line = $reader.ReadLine()
        } catch {
            # Transient read error on the pipe — don't kill the server.
            Start-Sleep -Milliseconds 500
            continue
        }
        if ($null -ne $line) {
            # Colour uvicorn's own startup/reload lines
            if ($line -match 'Application startup complete|Uvicorn running') {
                Write-Host $line -ForegroundColor Green
            } elseif ($line -match 'Reloading|WatchFiles') {
                Write-Host $line -ForegroundColor Yellow
            } elseif ($line -match 'ERROR|error') {
                Write-Host $line -ForegroundColor Red
            } else {
                Write-Host $line
            }
        } else {
            Start-Sleep -Milliseconds 200
        }
    }
} finally {
    if ($null -ne $reader) { $reader.Dispose() }
    if ($null -ne $fs)     { $fs.Dispose() }
    if (Test-Path $PipePath) { Remove-Item $PipePath -Force -ErrorAction SilentlyContinue }
    # Only kill the job if it's STILL running (i.e. we exited the loop due to
    # a read error, not because uvicorn actually stopped). If uvicorn exited
    # on its own, $job.HasExited is already true and Kill() is a no-op anyway —
    # but we check explicitly to avoid racing a healthy shutdown.
    try {
        if ($null -ne $job -and -not $job.HasExited) {
            Write-Host "Workbench tail loop exited but uvicorn still running — leaving it alone. Ctrl+C in this terminal to stop." -ForegroundColor Yellow
        }
    } catch {}
    Write-Host ""
    Write-Host "Workbench stopped. Worktree preserved at $WorktreeDir" -ForegroundColor Gray
    Write-Host "  Merge: git merge $WorktreeBranch" -ForegroundColor Cyan
    Write-Host "  Clean: .\dev-workbench.ps1 -Teardown" -ForegroundColor Cyan
}
