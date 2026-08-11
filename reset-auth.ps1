# AI Gator - Reset auth state for a clean cold test
#
# Clears ALL sign-in state: agent tokens (M365 FOCI, Teams Chat.ReadWrite, Slack
# OAuth), Electron webview partitions (Slack/Teams/Outlook cookies + localStorage),
# and stale caches - so you can test the sign-in flow from a true cold start.
#
# Keeps your LLM gateway config (~/.config/teamspoc/config.json) and MCP OAuth
# tokens (~/.gator/oauth/) intact - this is for app-auth testing, not a full wipe.
#
# Usage:
#   .\reset-auth.ps1              - clear everything, kill all running instances
#   .\reset-auth.ps1 -KeepRunning - clear state but leave running instances alone
#                                   (files held open by running processes may not delete)
#
# For a FULL reset (API key, onboarding, everything), see docs/BUILD_INSTRUCTIONS.md
# "Testing as a new user (clean slate)" instead.
param([switch]$KeepRunning)

$ErrorActionPreference = "SilentlyContinue"
$projectDir = $PSScriptRoot

Write-Host ""
Write-Host "=== AI Gator - Reset Auth State ===" -ForegroundColor Cyan

# ── 1. Stop running instances so file handles release ──────────────────────
# On Windows, open file handles block deletion. -ErrorAction SilentlyContinue on
# Remove-Item swallows the resulting "file in use" errors, leaving stale state
# behind - the #1 cause of "I cleared tokens but it still shows signed in".
if (-not $KeepRunning) {
    Write-Host "Stopping all AI Gator instances..." -ForegroundColor Yellow

    # Electron shell (both stable :8000 and dev :8003+ profiles)
    Get-CimInstance Win32_Process -Filter "Name='electron.exe' OR Name='AI Gator.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'gator-shell-' } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "  killed Electron PID $($_.ProcessId)" -ForegroundColor DarkGray
        }

    # Python backends: tray, watchdog, uvicorn (dev + stable)
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'aigator_tray|watchdog\.py|web\.app:app|dev\.ps1|uvicorn' } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "  killed Python PID $($_.ProcessId) ($($_.Name))" -ForegroundColor DarkGray
        }

    Start-Sleep -Seconds 2
    Write-Host "All instances stopped." -ForegroundColor Green
} else {
    Write-Host "Skipping process kill (-KeepRunning). Some files may not delete if held open." -ForegroundColor Yellow
}

# ── 2. Clear agent tokens (the "API" side of the dashboard) ────────────────
Write-Host "Clearing agent tokens..." -ForegroundColor Yellow

$mgDir = Join-Path $env:USERPROFILE ".config\microsoft-graph"
$slackDir = Join-Path $env:USERPROFILE ".config\slack-mcp"

$tokenFiles = @(
    (Join-Path $mgDir "token.json"),           # M365 FOCI (Mail/Calendar/Files/Teams chat)
    (Join-Path $mgDir "token.json.backup"),
    (Join-Path $mgDir "teams_token.json"),     # Teams Chat.ReadWrite (markChatRead/Unread)
    (Join-Path $mgDir "skype_token.json"),     # FOCI->Skype swap cache
    (Join-Path $mgDir "skypetoken.json"),      # legacy name
    (Join-Path $mgDir "teams_member_cache.json"),
    (Join-Path $slackDir "token.json"),         # Slack OAuth
    (Join-Path $slackDir ".pkce_pending.json"), # mid-flight OAuth state
    (Join-Path $slackDir "user_cache.json")
)

$cleared = 0; $failed = 0
foreach ($f in $tokenFiles) {
    if (Test-Path $f) {
        try {
            Remove-Item $f -Force
            $cleared++
        } catch {
            $failed++
            Write-Host "  could not delete (in use?): $f" -ForegroundColor DarkYellow
        }
    }
}
Write-Host "  Agent tokens: $cleared deleted, $failed skipped." -ForegroundColor Green

# ── 3. Clear Electron webview partitions (the "Web" side of the dashboard) ─
# Each port gets its own userData dir (gator-shell-<port>). Clear all known ports
# so stale state on :8000 doesn't leak into a :8003 dev test.
Write-Host "Clearing Electron webview partitions..." -ForegroundColor Yellow

$ports = @(8000, 8002, 8003)
$partitions = @("slack", "teams", "outlook")
$clearedParts = 0
foreach ($p in $ports) {
    $partRoot = Join-Path $env:APPDATA "gator-shell-$p\Partitions"
    if (-not (Test-Path $partRoot)) { continue }
    foreach ($part in $partitions) {
        $partPath = Join-Path $partRoot $part
        if (Test-Path $partPath) {
            try {
                Remove-Item $partPath -Recurse -Force
                $clearedParts++
            } catch {
                Write-Host "  could not delete (in use?): $partPath" -ForegroundColor DarkYellow
            }
        }
    }
}
Write-Host "  Partitions: $clearedParts deleted." -ForegroundColor Green

# ── 4. Verify ──────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Verification:" -ForegroundColor Cyan
$remaining = Get-ChildItem (Join-Path $mgDir "*.json") -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne "tool_schemas.json" }
if ($remaining) {
    Write-Host "  WARNING: token files still present:" -ForegroundColor Yellow
    $remaining | ForEach-Object { Write-Host "    $($_.Name)" -ForegroundColor DarkYellow }
} else {
    Write-Host "  Agent tokens: cleared" -ForegroundColor Green
}

$slackRemaining = Get-ChildItem (Join-Path $slackDir "*.json") -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne "tool_schemas.json" }
if ($slackRemaining) {
    Write-Host "  WARNING: Slack token files still present:" -ForegroundColor Yellow
    $slackRemaining | ForEach-Object { Write-Host "    $($_.Name)" -ForegroundColor DarkYellow }
} else {
    Write-Host "  Slack tokens: cleared" -ForegroundColor Green
}

$partRemaining = 0
foreach ($p in $ports) {
    $partRoot = Join-Path $env:APPDATA "gator-shell-$p\Partitions"
    if (Test-Path $partRoot) {
        $partRemaining += (Get-ChildItem $partRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -in $partitions }).Count
    }
}
if ($partRemaining -gt 0) {
    Write-Host "  WARNING: $partRemaining partition(s) still present" -ForegroundColor Yellow
} else {
    Write-Host "  Webview partitions: cleared" -ForegroundColor Green
}

# ── 5. Next steps ──────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Clean slate ready." -ForegroundColor Green
Write-Host ""
Write-Host "Next:" -ForegroundColor Cyan
Write-Host "  .\launch-dev.ps1            # dev instance on :8003" -ForegroundColor White
Write-Host "  .\launch-installed.ps1      # stable app on :8000" -ForegroundColor White
Write-Host ""
Write-Host "Then open Settings > Apps - dashboard should show all dots red/grey," -ForegroundColor DarkGray
Write-Host "'Not signed in' everywhere. Confirm with:" -ForegroundColor DarkGray
Write-Host "  curl http://localhost:8003/api/auth/status" -ForegroundColor DarkGray
Write-Host "  (should return: {`"authenticated`": false, `"reason`": `"No token file`"})" -ForegroundColor DarkGray
Write-Host ""
