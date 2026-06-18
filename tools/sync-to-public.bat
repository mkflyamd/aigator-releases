@echo off
setlocal enabledelayedexpansion
REM Syncs private main to public repo (aigator-releases) as a clean snapshot.
REM
REM Each release is ONE squashed commit (private git history is never exposed),
REM but the commit is parented on the EXISTING public history and pushed WITHOUT
REM --force. This preserves a continuous public ancestry so community fork PRs stay
REM mergeable/reopenable across releases. (The old orphan + force-push wiped history
REM every sync, which silently closed contributors' open PRs.)
REM
REM Usage: tools\sync-to-public.bat          (safe - blocks if public has unmerged commits)
REM        tools\sync-to-public.bat --force  (bypass community PR check - use when you know it's safe)

REM Move to repo root so all git commands run from there
cd /d "%~dp0.."

REM Parse --force flag (bypasses the community-PR warning only; the push is never forced)
set FORCE=0
if "%1"=="--force" set FORCE=1

REM Step 1: Fetch latest from public to detect unmerged community commits
echo Fetching from public repo...
git fetch public
if %errorlevel% neq 0 (
    echo Failed to fetch from public remote. Check your connection.
    goto :error
)

REM Determine whether public/main already exists (first sync vs. ongoing)
set HAVE_PUBLIC=0
git rev-parse --verify public/main >nul 2>&1
if %errorlevel%==0 set HAVE_PUBLIC=1

REM Step 2: Check for unmerged community commits on public/main
if %FORCE%==1 goto :do_sync
if %HAVE_PUBLIC%==0 goto :do_sync
set BEHIND=0
for /f %%i in ('git rev-list main..public/main --count') do set BEHIND=%%i
if !BEHIND! == 0 goto :do_sync
echo.
echo WARNING: public repo has !BEHIND! commit(s) not yet in your private main.
echo These are likely merged community PRs. Pull them first:
echo.
echo   git pull public main
echo.
echo Or if you are sure there are no community PRs to preserve, bypass with:
echo.
echo   tools\sync-to-public.bat --force
echo.
goto :error
:do_sync

REM Step 2.5: ASCII guard for the one-line installer scripts.
REM These are downloaded BOM-less and run via `iex`, which decodes them as
REM Windows-1252 — any non-ASCII char (e.g. an em-dash) becomes mojibake and
REM breaks PowerShell string parsing, hard-failing every fresh install. Block
REM the sync if WakeGator.ps1 / Get-AIGator.ps1 contain any non-ASCII byte.
echo Checking installer scripts for non-ASCII characters...
powershell -NoProfile -Command "$bad=0; foreach($f in @('WakeGator.ps1','Get-AIGator.ps1')){ if(Test-Path $f){ $raw=Get-Content -Raw $f; $m=[regex]::Matches($raw,'[^\x00-\x7F]'); if($m.Count -gt 0){ $bad=1; foreach($x in $m){ $ln=($raw.Substring(0,$x.Index) -split \"`n\").Count; Write-Host (\"  {0}: line {1} has non-ASCII U+{2:X4}\" -f $f,$ln,[int][char]$x.Value) } } } }; exit $bad"
if %errorlevel% neq 0 (
    echo.
    echo SYNC BLOCKED: an installer script contains non-ASCII characters ^(see above^).
    echo These break the one-line `iex` install. Replace them with ASCII equivalents
    echo ^(e.g. em-dash with a hyphen^) and re-run the sync.
    echo.
    goto :error
)
echo   OK - installer scripts are pure ASCII.

REM Step 3: Build the scrubbed snapshot on a throwaway branch off main.
REM Working on a temp branch keeps the destructive scrub off main itself.
echo Creating clean snapshot...
git checkout main
if %errorlevel% neq 0 goto :error
git checkout -B public-clean main
if %errorlevel% neq 0 goto :error

REM Delete private dirs from working tree before staging
if exist docs\internal rmdir /s /q docs\internal
if exist docs\superpowers rmdir /s /q docs\superpowers
if exist docs\screenshots rmdir /s /q docs\screenshots

REM Code-sign WakeGator.ps1 so testers can run it under RemoteSigned/AllSigned
REM policies without unblocking. Signs only this public snapshot; private stays clean.
if not exist build\AIGator_CodeSign.pfx goto :skip_sign
if defined AIGATOR_SIGN_PASSWORD goto :do_sign
set /p AIGATOR_SIGN_PASSWORD="Enter PFX password to sign WakeGator.ps1 (Enter to skip): "
if not defined AIGATOR_SIGN_PASSWORD goto :skip_sign
:do_sign
echo Signing WakeGator.ps1...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $c=New-Object System.Security.Cryptography.X509Certificates.X509Certificate2('build\AIGator_CodeSign.pfx', $env:AIGATOR_SIGN_PASSWORD); Set-AuthenticodeSignature -FilePath 'WakeGator.ps1' -Certificate $c -TimestampServer 'http://timestamp.digicert.com' -HashAlgorithm SHA256 | Out-Null"
if errorlevel 1 echo WARNING: Could not sign WakeGator.ps1 - continuing unsigned.
:skip_sign

REM Stage the scrubbed working tree into the index (adds, mods, and deletions)
git add -A
if %errorlevel% neq 0 goto :cleanup_error

REM Step 4: Snapshot the index as a tree, then commit it onto the EXISTING public
REM history. commit-tree lets us keep a one-commit-per-release public log (no private
REM history leak) while still chaining onto public/main so ancestry is preserved.
set TREE=
for /f %%t in ('git write-tree') do set TREE=%%t
if not defined TREE goto :cleanup_error

set PARENTARG=
if %HAVE_PUBLIC%==1 for /f %%p in ('git rev-parse public/main') do set PARENTARG=-p %%p

set NEWCOMMIT=
for /f %%c in ('git commit-tree !TREE! !PARENTARG! -m "feat: release"') do set NEWCOMMIT=%%c
if not defined NEWCOMMIT goto :cleanup_error

REM Step 5: Push the release commit to public main. No --force: this is a normal
REM fast-forward on top of public history, so existing community PRs survive.
echo Pushing to public repo...
git push public !NEWCOMMIT!:main
if %errorlevel% neq 0 (
    echo.
    echo Push was rejected. Public may have moved since the fetch above.
    echo Re-run the sync, or pull community commits first: git pull public main
    goto :cleanup_error
)

REM Step 6: Discard the scrubbed working state and clean up the temp branch
git checkout -f main
git branch -D public-clean
echo Done. Public repo updated (history preserved).
endlocal
exit /b 0

:cleanup_error
git checkout -f main 2>nul
git branch -D public-clean 2>nul
echo Push failed. Check errors above.
endlocal
exit /b 1

:error
git checkout main 2>nul
echo Sync failed. Check errors above.
endlocal
exit /b 1
