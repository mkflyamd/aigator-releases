@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set ROOT=%~dp0..

:: ══════════════════════════════════════════════════════════════════════════════
::  AI Gator Release Script
::  Runs tests, bumps version, builds installer (clean), tags, pushes,
::  uploads to GitHub Releases, updates manifest, verifies deployment.
::
::  Prerequisites:
::    - GitHub CLI (gh) installed and authenticated
::    - MinGW64 (gcc) on PATH — install via: winget install BrechtSanders.WinLibs.POSIX.UCRT
::    - Inno Setup 6 installed
::    - Python with Nuitka: pip install nuitka
:: ══════════════════════════════════════════════════════════════════════════════

:: ── Release repo config (change these if releasing from a different account) ─
set RELEASE_REPO=mkflyamd/aigator-releases
set PAGES_MANIFEST_URL=https://mkflyamd.github.io/aigator-releases/latest.json

echo.
echo  ======================================
echo   AI Gator Release
echo  ======================================
echo.

:: ── Pre-flight checks ────────────────────────────────────────────────────────
where gh >nul 2>nul
if errorlevel 1 (
    echo ERROR: GitHub CLI ^(gh^) not found. Install from https://cli.github.com
    exit /b 1
)
where curl >nul 2>nul
if errorlevel 1 (
    echo ERROR: curl not found.
    exit /b 1
)

:: ── Step 1: Run tests ────────────────────────────────────────────────────────
if /i "%~1"=="--skip-tests" (
    echo [1/8] Skipping tests ^(--skip-tests^).
    shift
    goto :tests_done
)
echo [1/8] Running tests...
python -m pytest "%ROOT%\tests" -q --tb=short --ignore="%ROOT%\tests\mcp" --deselect="tests/code_runner/test_run_python.py::test_packages_known_package_no_error"
if errorlevel 1 (
    echo.
    echo ERROR: Tests failed. Fix them before releasing.
    echo        To skip tests: release.bat --skip-tests
    exit /b 1
)
echo       All tests passed.
:tests_done
echo.

:: ── Read current version ─────────────────────────────────────────────────────
set /p CURRENT_VERSION=<"%ROOT%\version.txt"
if "%CURRENT_VERSION%"=="" (
    echo ERROR: version.txt is empty or missing.
    exit /b 1
)
echo  Current version: %CURRENT_VERSION%
echo.

:: ── Parse major.minor.patch ──────────────────────────────────────────────────
for /f "tokens=1-3 delims=." %%a in ("%CURRENT_VERSION%") do (
    set MAJOR=%%a
    set MINOR=%%b
    set PATCH=%%c
)

:: ── Calculate next versions ──────────────────────────────────────────────────
set /a NEXT_PATCH=%PATCH%+1
set /a NEXT_MINOR=%MINOR%+1
set /a NEXT_MAJOR=%MAJOR%+1

set OPT_PATCH=%MAJOR%.%MINOR%.%NEXT_PATCH%
set OPT_MINOR=%MAJOR%.%NEXT_MINOR%.0
set OPT_MAJOR=%NEXT_MAJOR%.0.0

echo  Choose next version:
echo.
echo    1) %OPT_PATCH%  (patch — bug fixes)
echo    2) %OPT_MINOR%  (minor — new features)
echo    3) %OPT_MAJOR%  (major — breaking changes)
echo    4) Custom
echo    5) %CURRENT_VERSION%  (rebuild current — no version change)
echo.
set /p CHOICE="  Your choice [1]: "
if "%CHOICE%"=="" set CHOICE=1

if "%CHOICE%"=="1" set NEW_VERSION=%OPT_PATCH%
if "%CHOICE%"=="2" set NEW_VERSION=%OPT_MINOR%
if "%CHOICE%"=="3" set NEW_VERSION=%OPT_MAJOR%
if "%CHOICE%"=="4" (
    set /p NEW_VERSION="  Enter version: "
)
if "%CHOICE%"=="5" (
    set NEW_VERSION=%CURRENT_VERSION%
    set SKIP_BUMP=1
)

if "%NEW_VERSION%"=="" (
    echo ERROR: No version entered.
    exit /b 1
)

if defined SKIP_BUMP (
    echo.
    echo  Rebuilding v%NEW_VERSION% ^(no version change^)
) else (
    echo.
    echo  %CURRENT_VERSION%  -^>  %NEW_VERSION%
)
echo.
set /p CONFIRM="  Proceed? [Y/n]: "
if /i "%CONFIRM%"=="n" (
    echo  Aborted.
    exit /b 0
)

:: ── Ask for release notes ────────────────────────────────────────────────────
echo.
set /p RELEASE_NOTES="  Release notes (one line): "
if "%RELEASE_NOTES%"=="" set RELEASE_NOTES=Bug fixes and improvements

if defined SKIP_BUMP (
    echo.
    echo [2/8] Skipping version bump ^(rebuild^).
    echo [3/8] Skipping commit and tag ^(rebuild^).
    echo [4/8] Skipping push ^(rebuild^).
    goto :do_build
)

:: ── Step 2: Bump version.txt ─────────────────────────────────────────────────
echo.
echo [2/8] Bumping version.txt to %NEW_VERSION%...
>"%ROOT%\version.txt" echo %NEW_VERSION%
echo       Done.

:: ── Step 3: Commit and tag ───────────────────────────────────────────────────
echo [3/8] Committing version bump and tagging v%NEW_VERSION%...
git -C "%ROOT%" add version.txt
git -C "%ROOT%" commit -m "chore: bump version to %NEW_VERSION%"
if errorlevel 1 echo       WARNING: Commit failed — maybe nothing changed?
git -C "%ROOT%" tag -a "v%NEW_VERSION%" -m "Release v%NEW_VERSION%"
if errorlevel 1 echo       WARNING: Tag v%NEW_VERSION% may already exist.
echo       Done.

:: ── Step 4: Push commit and tag to origin ────────────────────────────────────
echo [4/8] Pushing to origin...
git -C "%ROOT%" push -u origin main
if errorlevel 1 echo       WARNING: Push failed. You may need to push manually.
git -C "%ROOT%" push origin "v%NEW_VERSION%"
if errorlevel 1 echo       WARNING: Tag push failed. You may need to push manually.
echo       Done.

:do_build

:: ── Step 5: Clean build ──────────────────────────────────────────────────────
echo [5/8] Building installer (clean)...
:: Delete stale AIGator.exe so build.bat rebuilds from scratch
if exist "%~dp0AIGator.exe" (
    echo       Removing old AIGator.exe to force clean build...
    del /f "%~dp0AIGator.exe"
)
call "%~dp0build.bat" --build-only
if errorlevel 1 (
    echo ERROR: Build failed. Aborting release.
    exit /b 1
)

set INSTALLER=%~dp0dist\AIGatorInstaller.exe
if not exist "%INSTALLER%" (
    echo ERROR: Installer not found at %INSTALLER%
    exit /b 1
)

:: ── Step 6: Upload to GitHub Release ─────────────────────────────────────────
echo [6/8] Creating GitHub Release v%NEW_VERSION%...
echo.
echo  About to create release and upload installer:
echo    Tag:       v%NEW_VERSION%
echo    File:      %INSTALLER%
echo    Notes:     %RELEASE_NOTES%
echo    Repo:      %RELEASE_REPO%
echo.
set /p UPLOAD_CONFIRM="  Upload to GitHub? [Y/n]: "
if /i "%UPLOAD_CONFIRM%"=="n" (
    echo  Skipped upload. You can upload later with:
    echo    gh release create v%NEW_VERSION% "%INSTALLER%" --repo %RELEASE_REPO% --title "v%NEW_VERSION%" --notes "%RELEASE_NOTES%"
    goto :update_manifest_skip
)

gh release create "v%NEW_VERSION%" "%INSTALLER%" --repo %RELEASE_REPO% --title "v%NEW_VERSION%" --notes "%RELEASE_NOTES%"
if errorlevel 1 (
    echo ERROR: GitHub release creation failed.
    exit /b 1
)
echo       Done.

:: ── Step 7: Update latest.json on gh-pages ───────────────────────────────────
echo [7/8] Updating latest.json manifest...

set MANIFEST_DIR=%TEMP%\aigator-releases-ghpages
if exist "%MANIFEST_DIR%" rd /s /q "%MANIFEST_DIR%"

git clone --branch gh-pages --single-branch --depth 1 https://github.com/%RELEASE_REPO%.git "%MANIFEST_DIR%"
if errorlevel 1 (
    echo ERROR: Could not clone gh-pages branch.
    exit /b 1
)

(
echo {
echo   "version": "%NEW_VERSION%",
echo   "url": "https://github.com/%RELEASE_REPO%/releases/download/v%NEW_VERSION%/AIGatorInstaller.exe",
echo   "notes": "%RELEASE_NOTES%"
echo }
) > "%MANIFEST_DIR%\latest.json"

git -C "%MANIFEST_DIR%" add latest.json
git -C "%MANIFEST_DIR%" commit -m "update manifest to v%NEW_VERSION%"
git -C "%MANIFEST_DIR%" push
if errorlevel 1 (
    echo ERROR: Could not push manifest update.
    exit /b 1
)
rd /s /q "%MANIFEST_DIR%"
echo       Done.

:: ── Step 8: Verify manifest is live ──────────────────────────────────────────
echo [8/8] Verifying manifest deployment...
:: GitHub Pages can take a few seconds to update
echo       Waiting for GitHub Pages to update...
timeout /t 10 /nobreak >nul

curl -s "%PAGES_MANIFEST_URL%" > "%TEMP%\aigator-manifest-check.json" 2>nul
if errorlevel 1 (
    echo       WARNING: Could not fetch manifest. Check manually: %PAGES_MANIFEST_URL%
    goto :release_done
)

:: Extract version from manifest and compare
for /f "tokens=2 delims=:," %%v in ('findstr /c:"version" "%TEMP%\aigator-manifest-check.json"') do (
    set MANIFEST_VERSION=%%~v
)
:: Trim spaces
for /f "tokens=* delims= " %%a in ("!MANIFEST_VERSION!") do set MANIFEST_VERSION=%%a

if "!MANIFEST_VERSION!"=="%NEW_VERSION%" (
    echo       Manifest verified: v%NEW_VERSION% is live.
) else (
    echo       WARNING: Manifest shows "!MANIFEST_VERSION!" but expected "%NEW_VERSION%".
    echo       GitHub Pages may need a minute to propagate. Check: %PAGES_MANIFEST_URL%
)
del "%TEMP%\aigator-manifest-check.json" 2>nul

goto :release_done

:update_manifest_skip
echo  Skipped manifest update (upload was skipped).

:release_done
echo.
echo  ======================================
echo   Release v%NEW_VERSION% complete!
echo  ======================================
echo.
echo   Version bumped:  %CURRENT_VERSION% -^> %NEW_VERSION%
echo   Git tag:         v%NEW_VERSION%
echo   Installer:       build\dist\AIGatorInstaller.exe
echo   GitHub Release:  https://github.com/%RELEASE_REPO%/releases/tag/v%NEW_VERSION%
echo   Manifest:        %PAGES_MANIFEST_URL%
echo.
