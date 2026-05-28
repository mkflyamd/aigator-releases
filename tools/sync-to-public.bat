@echo off
REM Syncs private main to public repo (aigator-releases) with no history.
REM Usage: tools\sync-to-public.bat          (safe - blocks if public has unmerged commits)
REM        tools\sync-to-public.bat --force  (bypass community PR check - use when you know it's safe)

REM Move to repo root so all git commands run from there
cd /d "%~dp0.."

REM Parse --force flag
set FORCE=0
if "%1"=="--force" set FORCE=1

REM Step 1: Fetch latest from public to detect unmerged community commits
echo Fetching from public repo...
git fetch public
if %errorlevel% neq 0 (
    echo Failed to fetch from public remote. Check your connection.
    goto :error
)

REM Step 2: Check for unmerged community commits on public/main
if %FORCE%==1 goto :do_sync
set BEHIND=0
git rev-parse public/main >nul 2>&1
if %errorlevel% neq 0 goto :do_sync
for /f %%i in ('git rev-list main..public/main --count') do set BEHIND=%%i
if %BEHIND% == 0 goto :do_sync
echo.
echo WARNING: public repo has %BEHIND% commit(s) not yet in your private main.
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

REM Step 3: Create a fresh orphan snapshot of main (no history)
echo Creating clean snapshot...
git checkout main
git checkout --orphan public-clean
if %errorlevel% neq 0 goto :error

REM Delete private dirs from working tree before staging
if exist docs\internal rmdir /s /q docs\internal
if exist docs\superpowers rmdir /s /q docs\superpowers
if exist docs\screenshots rmdir /s /q docs\screenshots

git add -A
git commit -m "feat: release"
if %errorlevel% neq 0 goto :cleanup_error

REM Step 4: Force push the clean snapshot to public repo
echo Pushing to public repo...
git push public public-clean:main --force
if %errorlevel% neq 0 goto :cleanup_error

REM Step 5: Delete temp branch and return to main
git checkout main
git branch -D public-clean
echo Done. Public repo updated.
exit /b 0

:cleanup_error
git checkout main 2>nul
git branch -D public-clean 2>nul
echo Push failed. Check errors above.
exit /b 1

:error
git checkout main 2>nul
echo Sync failed. Check errors above.
exit /b 1
