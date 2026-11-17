# AI Gator - Dev Electron Shell Launcher
#
# AI Gator's UI runs inside the Electron shell (shell/main.js) - there is no
# browser. This launcher opens the dev Electron shell ATTACHED to a running dev
# backend so you can see/test the native Slack/Teams/Outlook panes.
#
# Two-terminal workflow:
#   Terminal A - the STABLE build:      .\dev.ps1                 (backend :8000)
#   Terminal B - the WORKTREE:          .\dev-workbench.ps1       (backend :8002)
#   Then point the shell at whichever you want to look at:
#     .\dev-shell.ps1              - attach to the worktree   (:8002, default)
#     .\dev-shell.ps1 -Port 8000   - attach to the stable build (:8000)
#
# GATOR_URL pins the shell to that backend so it ATTACHES instead of spawning its
# own (see shell/main.js SPAWN_BACKEND gate). The shell ALWAYS launches with
# --remote-debugging-port=9222 so the Chrome DevTools MCP can attach.
#
# Usage:
#   .\dev-shell.ps1                    - attach to :8002 (worktree)
#   .\dev-shell.ps1 -Port 8000         - attach to :8000 (stable)
#   .\dev-shell.ps1 -DebugPort 9223    - use a different remote-debugging port
#   .\dev-shell.ps1 -Restart           - close the shell already open for the port
#                                        and launch a fresh one (default: leave it)
param(
    [int]$Port = 8002,
    [int]$DebugPort = 9222,
    [switch]$Restart
)

$projectDir = $PSScriptRoot
$shellDir   = Join-Path $projectDir "shell"
$electron   = Join-Path $shellDir "node_modules\electron\dist\electron.exe"

Write-Host ""
Write-Host "=== AI Gator Dev Shell ===" -ForegroundColor Cyan
Write-Host "  Backend      : http://localhost:$Port" -ForegroundColor Green
Write-Host "  Debug (MCP)  : http://localhost:$DebugPort" -ForegroundColor DarkGray
Write-Host ""

# Ensure the dev Electron is installed in shell/ (deleted during clean tests /
# fresh clones). This is the SAME Electron the shell's package.json pins.
if (-not (Test-Path $electron)) {
    Write-Host "Installing shell/ dev dependencies (first run)..." -ForegroundColor Yellow
    Push-Location $shellDir
    & npm install
    Pop-Location
}
if (-not (Test-Path $electron)) {
    Write-Host "Could not find Electron at:" -ForegroundColor Red
    Write-Host "  $electron" -ForegroundColor Red
    Write-Host "Run 'npm install' in shell\ manually, then re-run dev-shell.ps1." -ForegroundColor Yellow
    exit 1
}

# Find the Electron for THIS port only, so a stable app (or another dev instance)
# on a different port is never touched. shell/main.js scopes its userData profile
# to "gator-shell-<port>" (see app.setPath), and EVERY process of that instance
# (main + gpu/renderer/utility children) carries it as --user-data-dir.
$profileTag = "gator-shell-$Port"
$existing = @(Get-CimInstance Win32_Process -Filter "Name='electron.exe' OR Name='AI Gator.exe'" -OperationTimeoutSec 10 -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match [regex]::Escape($profileTag) })
if ($existing.Count -gt 0) {
    if (-not $Restart) {
        Write-Host "A shell for :$Port is already open - leaving it running (use -Restart to relaunch)." -ForegroundColor Green
        exit 0
    }
    Write-Host "Stopping the running Electron for :$Port ..." -ForegroundColor Yellow
    $existing | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}

# Attach the shell to the chosen backend. ALWAYS enable remote debugging so the
# Chrome DevTools MCP can connect (dev only - production launchers never do this).
# GATOR_DEV makes the window title read "AI Gator [DEV] :<port>" so a dev window
# is instantly distinguishable from the stable app (prod never sets it).
$env:GATOR_URL = "http://localhost:$Port"
$env:GATOR_DEV = "1"
Start-Process -FilePath $electron `
    -ArgumentList $shellDir, "--remote-debugging-port=$DebugPort" `
    -WorkingDirectory $shellDir

Start-Sleep -Seconds 8
Write-Host "Launched (attached to :$Port, debugging on :$DebugPort)." -ForegroundColor Green
