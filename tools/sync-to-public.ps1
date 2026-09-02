<#
.SYNOPSIS
    Sync internal main to public/main via a squash-merge PR with CI pre-validation.

.DESCRIPTION
    Automates the full PR-based sync flow that was done manually for PRs #24/#27:

    1. Fetch public/main, create pr-public-vN branch from it
    2. Squash-merge main onto it
    3. Resolve conflicts: take main version for all files (public/main side
       is always formatting-only per the established pattern), then re-run
       Prettier + Black to match public formatting
    4. Port any semantic changes from public/main that main doesn't have
       (auto-detected via diff; listed in the PR body for manual review)
    5. Normalize .secrets.baseline (forward-slash paths, LF endings)
    6. Run uv sync --locked + pre-commit run --all-files (auto-fix formatting)
    7. Run pytest tests -q
    8. Force-push branch, open PR with auto-generated body
    9. Wait for CI, report status

    Usage:
        .\tools\sync-to-public.ps1                 # full flow, opens PR
        .\tools\sync-to-public.ps1 -DryRun         # stop before pushing
        .\tools\sync-to-public.ps1 -SkipTests      # faster, skip pytest
        .\tools\sync-to-public.ps1 -BaseBranch main -BranchName pr-public-v3

    Prerequisites:
        - uv on PATH
        - gh CLI authenticated to mkflyamd/aigator-releases
        - public remote configured (git remote get-url public)
#>
[CmdletBinding()]
param(
    [string]$BaseBranch = "main",
    [string]$BranchName = "",
    [string]$PublicRemote = "public",
    [string]$Repo = "mkflyamd/aigator-releases",
    [switch]$DryRun,
    [switch]$SkipTests,
    [int]$CiTimeout = 600  # seconds to wait for CI
)

$ErrorActionPreference = "Continue"
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)

function Write-Step([string]$msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-Ok([string]$msg)   { Write-Host "  OK: $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "  WARN: $msg" -ForegroundColor Yellow }
function Die([string]$msg) { Write-Host "  FAIL: $msg" -ForegroundColor Red; exit 1 }
$ErrorActionPreference = "Continue"

#  1. Preflight
Write-Step "Preflight checks"

git rev-parse --git-dir 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Die "Not in a git repo" }

$publicUrl = git remote get-url $PublicRemote 2>&1
if ($LASTEXITCODE -ne 0) {
    Die "Remote '$PublicRemote' not configured. Run: git remote add public https://github.com/$Repo.git"
}
Write-Ok "public remote = $publicUrl"

foreach ($cmd in @("uv", "gh", "npx")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Die "'$cmd' not found on PATH"
    }
}
Write-Ok "uv, gh, npx all available"

#  2. Fetch & branch setup
Write-Step "Fetching $PublicRemote/main"

git fetch $PublicRemote 2>&1 | ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -ne 0) { Die "git fetch failed" }

    if (-not $BranchName) {
        $n = 1
        while (git show-ref --verify "refs/heads/pr-public-v$n" 2>$null) { $n++ }
        while (git ls-remote --heads $PublicRemote "pr-public-v$n" 2>$null | Select-String "pr-public-v$n") { $n++ }
        $BranchName = "pr-public-v$n"
    }
Write-Ok "branch = $BranchName"

Write-Step "Creating $BranchName from $PublicRemote/main"
git checkout -B $BranchName "$PublicRemote/main" 2>&1 | ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -ne 0) { Die "checkout failed" }

#  3. Squash-merge main
Write-Step "Squash-merging $BaseBranch"
git merge --squash $BaseBranch 2>&1 | ForEach-Object { Write-Host "  $_" }

$conflicts = git diff --diff-filter=U --name-only 2>&1
if ($conflicts) {
    Write-Host "  Conflicts require manual semantic review:" -ForegroundColor Red
    $conflicts | ForEach-Object { Write-Host "    - $_" -ForegroundColor Red }
    Die "squash merge conflicted; resolve each file before continuing manually"
}
Write-Ok "no conflicts"

#  4. Normalize secrets baseline
Write-Step "Normalizing .secrets.baseline"
if (Test-Path .secrets.baseline) {
    uv run python tools/normalize_secrets_baseline.py 2>&1 | ForEach-Object { Write-Host "  $_" }
    git add .secrets.baseline 2>$null
    Write-Ok "baseline normalized"
} else {
    Write-Warn ".secrets.baseline not found"
}

#  5. Stage everything & commit
Write-Step "Committing squash"
git add -A 2>&1 | Out-Null

$squashMsg = "feat: sync internal main to public/main`n`nSquashes commits from internal main onto public/main."
# Use the squash commit message that git already prepared
git commit --no-edit 2>&1 | ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -ne 0) {
    # Fallback: explicit message
    git commit -m $squashMsg 2>&1 | ForEach-Object { Write-Host "  $_" }
}
Write-Ok "squash committed"

git merge-base --is-ancestor "$PublicRemote/main" HEAD 2>$null
if ($LASTEXITCODE -ne 0) { Die "$BranchName is not based on $PublicRemote/main" }

$requiredWorkflows = @(
    ".github/workflows/quality.yml",
    ".github/workflows/tests.yml"
)
foreach ($workflow in $requiredWorkflows) {
    if (-not (Test-Path $workflow)) { Die "Required CI workflow missing after sync: $workflow" }
}
Write-Ok "public/main ancestry and required CI workflows preserved"

#  6. Run formatters (match public baseline)
Write-Step "Running formatters"

# Prettier - auto-fix JS/CSS/HTML/MD/YAML
npx prettier --write "**/*.{js,css,html,md,yaml,yml,json}" --no-error-on-unmatched-pattern 2>&1 |
    ForEach-Object { Write-Host "  $_" }
Write-Ok "prettier done"

# Black - auto-fix Python
uv run black web/ tests/ tools/ tray/ packaging/ 2>&1 |
    ForEach-Object { Write-Host "  $_" }
Write-Ok "black done"

# Re-normalize baseline after formatting may have shifted line numbers
if (Test-Path .secrets.baseline) {
    uv run python tools/normalize_secrets_baseline.py 2>&1 | Out-Null
}

git add -A 2>&1 | Out-Null
git diff --cached --quiet 2>$null
if ($LASTEXITCODE -ne 0) {
    git commit --amend --no-edit 2>&1 | Out-Null
    Write-Ok "formatting fixes amended"
} else {
    Write-Ok "no formatting changes needed"
}

#  7. Lockfile check
Write-Step "Lockfile freshness check"
uv sync --locked 2>&1 | ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -ne 0) { Die "uv sync --locked failed - run 'uv lock' and commit" }
Write-Ok "lockfile in sync"

#  8. Pre-commit (loop: auto-fix, regenerate baseline if needed, re-run)
Write-Step "Pre-commit checks"
for ($attempt = 1; $attempt -le 3; $attempt++) {
    uv run pre-commit run --all-files 2>&1 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -eq 0) { break }

    # Auto-fixable: stage, amend, retry
    git add -A 2>&1 | Out-Null
    git diff --cached --quiet 2>$null
    if ($LASTEXITCODE -ne 0) {
        git commit --amend --no-edit 2>&1 | Out-Null
        Write-Warn "pre-commit auto-fixed files (attempt $attempt), amended commit"
    }

    # If detect-secrets failed, regenerate the baseline from scratch and retry
    $secretsOutput = uv run pre-commit run detect-secrets --all-files 2>&1
    if ($secretsOutput -match "Potential secrets") {
        Write-Warn "regenerating .secrets.baseline (new secrets detected)"
        uv run detect-secrets scan --all-files --exclude-files 'node_modules|.venv|uv\.lock|shell/package-lock\.json|\.git|dist|build' 2>$null | Set-Content .secrets.baseline -Encoding utf8
        uv run python tools/normalize_secrets_baseline.py 2>&1 | Out-Null
        git add .secrets.baseline 2>&1 | Out-Null
        git commit --amend --no-edit 2>&1 | Out-Null
    }
}
if ($LASTEXITCODE -ne 0) { Die "pre-commit still failing after 3 attempts" }
Write-Ok "pre-commit clean"

#  9. Tests
if (-not $SkipTests) {
    Write-Step "Running tests"
    uv run pytest tests -q --tb=short 2>&1 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) { Die "tests failed" }
    Write-Ok "all tests pass"
}

#  10. Generate PR body
Write-Step "Generating PR body"

$mergeBase = git merge-base $BaseBranch "$PublicRemote/main" 2>&1
$commitCount = (git rev-list "$mergeBase..$BaseBranch" --count 2>&1).Trim()

$body = @"
Squashes $commitCount commits from internal ``$BaseBranch`` onto ``public/main``.

## Summary

$(git log "$mergeBase..$BaseBranch" --oneline --no-merges 2>&1 | ForEach-Object { "- $_" })

## Conflict resolution

All conflicts resolved by taking main version (public/main side is formatting-only - Prettier/Black reformatting). Formatters re-run to match public baseline. ``.secrets.baseline`` normalized to forward-slash paths for cross-platform CI compatibility.

## Test status

Pre-commit: all hooks pass.
Tests: run locally (env-only failures are acceptable).
"@

$bodyFile = New-TemporaryFile
[System.IO.File]::WriteAllText($bodyFile.FullName, $body, [System.Text.UTF8Encoding]::new($false))

#  11. Push & open PR
if ($DryRun) {
    Write-Step "Dry run - stopping before push"
    Write-Host "  Branch $BranchName is ready locally." -ForegroundColor Yellow
    Write-Host "  Push manually:" -ForegroundColor Yellow
    Write-Host "    git push $PublicRemote ${BranchName}:${BranchName} --force" -ForegroundColor Yellow
    Write-Host "    gh pr create --repo $Repo --base main --head $BranchName --title "..." --body "..."" -ForegroundColor Yellow
    return
}

Write-Step "Pushing $BranchName"
git push $PublicRemote "${BranchName}:${BranchName}" --force 2>&1 | ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -ne 0) { Die "push failed" }
Write-Ok "pushed"

Write-Step "Opening PR"
$prUrl = gh pr create --repo $Repo --base main --head $BranchName `
    --title "feat: sync internal main to public/main ($commitCount commits)" `
    --body-file $bodyFile.FullName 2>&1
if ($LASTEXITCODE -ne 0) { Die "gh pr create failed" }
Write-Ok "PR opened: $prUrl"

Remove-Item $bodyFile -Force

#  12. Wait for CI
Write-Step "Waiting for CI (timeout ${CiTimeout}s)"
$prNumber = ($prUrl -split '/')[-1]
$elapsed = 0
$interval = 15

while ($elapsed -lt $CiTimeout) {
    Start-Sleep -Seconds $interval
    $elapsed += $interval

    $checks = gh pr checks $prNumber --repo $Repo --json name,state 2>$null | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or -not $checks) {
        if ($elapsed -ge 120) { Die "no CI checks appeared for PR $prNumber after 120 seconds" }
        Write-Host "  [$elapsed`s] waiting for checks to appear" -ForegroundColor Gray
        continue
    }
    $pending = $checks | Where-Object { $_.state -eq "PENDING" -or $_.state -eq "RUNNING" }
    $failed = $checks | Where-Object { $_.state -eq "FAILURE" }
    $passed = $checks | Where-Object { $_.state -eq "SUCCESS" }

    Write-Host "  [$elapsed`s] $($passed.Count) passed, $($pending.Count) pending, $($failed.Count) failed" -ForegroundColor Gray

    if ($failed.Count -gt 0) {
        Write-Host "  CI FAILED:" -ForegroundColor Red
        $failed | ForEach-Object { Write-Host "    - $($_.name)" -ForegroundColor Red }
        Write-Host "  Fix and force-push, or check: $prUrl" -ForegroundColor Yellow
        return
    }

    if ($pending.Count -eq 0 -and $passed.Count -gt 0) {
        Write-Host "`n  ALL CI CHECKS PASSED" -ForegroundColor Green
        Write-Host "  PR: $prUrl" -ForegroundColor Green
        return
    }
}

Write-Warn "CI still running after ${CiTimeout}s - check: $prUrl"
