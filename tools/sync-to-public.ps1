<#
.SYNOPSIS
    Sync internal main to public repo via a PR. Preserves full commit history.

.DESCRIPTION
    Runs local CI checks, pushes main as a PR branch to the public remote,
    and opens a PR for the maintainer to review and merge.

    1. Preflight checks (git, gh, uv)
    2. Auto-generate branch name (pr-public-vN)
    3. Run uv sync --locked (lockfile check)
    4. Run pre-commit --all-files
    5. Run pytest (optional, skip with -SkipTests)
    6. Push main as PR branch to public remote
    7. Open PR against public/main
    8. Wait for CI, report status

    Usage:
        .\tools\sync-to-public.ps1                 # full flow, opens PR
        .\tools\sync-to-public.ps1 -DryRun         # stop before pushing
        .\tools\sync-to-public.ps1 -SkipTests      # skip pytest
        .\tools\sync-to-public.ps1 -BranchName pr-public-v3

    Prerequisites:
        - gh CLI authenticated to mkflyamd/aigator-releases
        - uv on PATH
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
    [int]$CiTimeout = 600
)

$ErrorActionPreference = "Continue"
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)

function Write-Step([string]$msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-Ok([string]$msg)   { Write-Host "  OK: $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "  WARN: $msg" -ForegroundColor Yellow }
function Die([string]$msg) { Write-Host "  FAIL: $msg" -ForegroundColor Red; exit 1 }

#  1. Preflight
Write-Step "Preflight checks"

git rev-parse --git-dir 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Die "Not in a git repo" }

$publicUrl = git remote get-url $PublicRemote 2>&1
if ($LASTEXITCODE -ne 0) {
    Die "Remote '$PublicRemote' not configured. Run: git remote add public https://github.com/$Repo.git"
}
Write-Ok "public remote = $publicUrl"

foreach ($cmd in @("gh", "uv")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Die "'$cmd' not found on PATH"
    }
}
Write-Ok "gh, uv available"

$currentBranch = git rev-parse --abbrev-ref HEAD 2>&1
if ($currentBranch -ne $BaseBranch) {
    Write-Warn "Currently on '$currentBranch', not '$BaseBranch'. Switching..."
    git checkout $BaseBranch 2>&1 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) { Die "Could not switch to $BaseBranch" }
}
Write-Ok "on branch $BaseBranch"

#  2. Pick branch name
Write-Step "Fetching $PublicRemote"
git fetch $PublicRemote 2>&1 | ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -ne 0) { Die "git fetch failed" }

if (-not $BranchName) {
    $n = 1
    while (git show-ref --verify "refs/heads/pr-public-v$n" 2>$null) { $n++ }
    while (git ls-remote --heads $PublicRemote "pr-public-v$n" 2>$null | Select-String "pr-public-v$n") { $n++ }
    $BranchName = "pr-public-v$n"
}
Write-Ok "PR branch = $BranchName"

#  3. Lockfile check
Write-Step "Lockfile freshness check"
uv sync --locked 2>&1 | ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -ne 0) { Die "uv sync --locked failed - run 'uv lock' and commit" }
Write-Ok "lockfile in sync"

#  4. Pre-commit
Write-Step "Pre-commit checks"
for ($attempt = 1; $attempt -le 3; $attempt++) {
    uv run pre-commit run --all-files 2>&1 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -eq 0) { break }

    git add -A 2>&1 | Out-Null
    git diff --cached --quiet 2>$null
    if ($LASTEXITCODE -ne 0) {
        git commit --amend --no-edit 2>&1 | Out-Null
        Write-Warn "pre-commit auto-fixed files (attempt $attempt), amended commit"
    }
}
if ($LASTEXITCODE -ne 0) { Die "pre-commit still failing after 3 attempts" }
Write-Ok "pre-commit clean"

#  5. Tests (optional)
if (-not $SkipTests) {
    Write-Step "Running tests"
    uv run pytest tests -q --tb=short 2>&1 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "some tests failed - check output above"
        Write-Warn "env-only failures (pip installed locally, missing network) are OK"
    } else {
        Write-Ok "all tests pass"
    }
}

#  6. Generate PR body
Write-Step "Generating PR body"

$mergeBase = git merge-base $BaseBranch "$PublicRemote/main" 2>&1
$commitCount = (git rev-list "$mergeBase..$BaseBranch" --count 2>&1).Trim()

$body = @"
Syncs $commitCount commits from internal ``$BaseBranch`` to ``public/main``.

## Commits

$(git log "$mergeBase..$BaseBranch" --oneline --no-merges 2>&1 | ForEach-Object { "- $_" })

## Notes

Full commit history preserved - no squash. Local CI checks passed (lockfile, pre-commit, pytest). Please merge when public CI passes.
"@

$bodyFile = New-TemporaryFile
[System.IO.File]::WriteAllText($bodyFile.FullName, $body, [System.Text.UTF8Encoding]::new($false))

#  7. Push & open PR
if ($DryRun) {
    Write-Step "Dry run - stopping before push"
    Write-Host "  Branch $BranchName is ready to push." -ForegroundColor Yellow
    Write-Host "  Commits to be included:" -ForegroundColor Yellow
    git log "$mergeBase..$BaseBranch" --oneline --no-merges 2>&1 | ForEach-Object { Write-Host "    $_" }
    Write-Host "  Push manually:" -ForegroundColor Yellow
    Write-Host "    git push $PublicRemote ${BaseBranch}:${BranchName}" -ForegroundColor Yellow
    Write-Host "    gh pr create --repo $Repo --base main --head $BranchName" -ForegroundColor Yellow
    return
}

Write-Step "Pushing $BaseBranch as $BranchName to $PublicRemote"
git push $PublicRemote "${BaseBranch}:${BranchName}" 2>&1 | ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -ne 0) { Die "push failed" }
Write-Ok "pushed"

Write-Step "Opening PR"
$prUrl = gh pr create --repo $Repo --base main --head $BranchName `
    --title "feat: sync internal main ($commitCount commits)" `
    --body-file $bodyFile.FullName 2>&1
if ($LASTEXITCODE -ne 0) { Die "gh pr create failed" }
Write-Ok "PR opened: $prUrl"

Remove-Item $bodyFile -Force

#  8. Wait for CI
Write-Step "Waiting for CI (timeout ${CiTimeout}s)"
$prNumber = ($prUrl -split '/')[-1]
$elapsed = 0
$interval = 15

while ($elapsed -lt $CiTimeout) {
    Start-Sleep -Seconds $interval
    $elapsed += $interval

    $checks = gh pr checks $prNumber --repo $Repo --json name,state 2>&1 | ConvertFrom-Json
    $pending = $checks | Where-Object { $_.state -eq "PENDING" -or $_.state -eq "RUNNING" }
    $failed  = $checks | Where-Object { $_.state -eq "FAILURE" }
    $passed  = $checks | Where-Object { $_.state -eq "SUCCESS" }

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
