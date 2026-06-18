@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: Skip menu when called from release.bat
if "%1"=="--build-only" goto :do_build

:: Read current version
set ROOT=%~dp0..
set /p APP_VERSION=<"%ROOT%\version.txt"

echo.
echo  ======================================
echo   AI Gator Dev Tools   v%APP_VERSION%
echo  ======================================
echo.
echo   1. Build installer
echo   2. Sync to public repo
echo   3. Build + Sync to public
echo   4. Full release (tests + version + build + GitHub upload)
echo   5. Exit
echo.
set /p CHOICE="  Select an option (1-5): "

if "%CHOICE%"=="1" goto :build
if "%CHOICE%"=="2" goto :sync
if "%CHOICE%"=="3" goto :build_and_sync
if "%CHOICE%"=="4" goto :release
if "%CHOICE%"=="5" exit /b 0
echo Invalid choice. Exiting.
exit /b 1

:: -----------------------------------------------------------------------------
:build_and_sync
call :do_build
if %errorlevel% neq 0 exit /b 1
goto :sync

:build
call :do_build
exit /b %errorlevel%

:release
echo.
call "%~dp0release.bat"
exit /b %errorlevel%

:sync
echo.
echo  ======================================
echo   Syncing to public repo...
echo  ======================================
echo.
set SYNC_FLAG=
set /p SYNC_CONFIRM="  Use --force to bypass community PR check? (y/N): "
if /i "%SYNC_CONFIRM%"=="y" set SYNC_FLAG=--force
call "%~dp0..\tools\sync-to-public.bat" %SYNC_FLAG%
exit /b %errorlevel%

:: -----------------------------------------------------------------------------
:do_build
echo.
echo  ======================================
echo   AI Gator Build Script
echo  ======================================
echo.

:: -- Config -------------------------------------------------------------------
set PYTHON_VERSION=3.12.10
set PYTHON_ZIP=python-%PYTHON_VERSION%-embed-amd64.zip
set PYTHON_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/%PYTHON_ZIP%
set PYDIR=%~dp0python_dist
set PIP_BOOTSTRAP=https://bootstrap.pypa.io/get-pip.py
:: Auto-detect Inno Setup location
set ISCC=
for /f "delims=" %%i in ('where /r "C:\Program Files (x86)" ISCC.exe 2^>nul') do set ISCC="%%i"
for /f "delims=" %%i in ('where /r "C:\Program Files" ISCC.exe 2^>nul') do if not defined ISCC set ISCC="%%i"
for /f "delims=" %%i in ('where /r "%LOCALAPPDATA%" ISCC.exe 2^>nul') do if not defined ISCC set ISCC="%%i"
for /f "delims=" %%i in ('where /r "%APPDATA%" ISCC.exe 2^>nul') do if not defined ISCC set ISCC="%%i"
set ROOT=%~dp0..
:: Strip trailing backslash from BUILDDIR to avoid quote-escaping bug
set BUILDDIR=%~dp0
set BUILDDIR=%BUILDDIR:~0,-1%

:: -- Code signing config ------------------------------------------------------
set PFX_FILE=%BUILDDIR%\AIGator_CodeSign.pfx
set SIGN_THUMBPRINT=B09F5EF43A1D7BF0F97C4883D723BA1AF67A7F42
:: Set AIGATOR_SIGN_PASSWORD env var or pass as first argument
if not "%~1"=="" if not "%~1"=="--build-only" set PFX_PASSWORD=%~1
if not defined PFX_PASSWORD set PFX_PASSWORD=%AIGATOR_SIGN_PASSWORD%

:: Auto-detect signtool — try PATH first, then Windows Kits (x64 variant)
set SIGNTOOL=
for /f "delims=" %%i in ('where signtool 2^>nul') do set SIGNTOOL="%%i"
if not defined SIGNTOOL (
    for /f "delims=" %%i in ('where /r "C:\Program Files (x86)\Windows Kits\10\bin" signtool.exe 2^>nul ^| findstr "\\x64\\"') do set SIGNTOOL="%%i"
)

:: -- Step 1: Download embedded Python if not present --------------------------
echo [1/6] Checking embedded Python...
if exist "%PYDIR%\python.exe" (
    echo       Already present. Skipping download.
) else (
    echo       Downloading Python %PYTHON_VERSION% embeddable...
    if not exist "%~dp0%PYTHON_ZIP%" (
        curl -L -o "%~dp0%PYTHON_ZIP%" "%PYTHON_URL%"
        if errorlevel 1 ( echo ERROR: Download failed. & exit /b 1 )
    )
    echo       Extracting...
    tar -xf "%~dp0%PYTHON_ZIP%" -C "%PYDIR%\" 2>nul || (
        md "%PYDIR%" 2>nul
        powershell -Command "Expand-Archive -Path '%~dp0%PYTHON_ZIP%' -DestinationPath '%PYDIR%' -Force"
    )
    if errorlevel 1 ( echo ERROR: Extraction failed. & exit /b 1 )
    echo       Done.
)

:: -- Step 2: Enable site-packages in embedded Python --------------------------
echo [2/6] Configuring embedded Python...
set PTH_FILE=%PYDIR%\python312._pth
if exist "%PTH_FILE%" (
    powershell -Command "(Get-Content '%PTH_FILE%') -replace '#import site','import site' | Set-Content '%PTH_FILE%'"
)
if not exist "%PYDIR%\Scripts\pip.exe" (
    echo       Installing pip...
    curl -sSL "%PIP_BOOTSTRAP%" -o "%TEMP%\get-pip.py"
    "%PYDIR%\python.exe" "%TEMP%\get-pip.py" --no-warn-script-location
    if errorlevel 1 ( echo ERROR: pip install failed. & exit /b 1 )
)
echo       Done.

:: -- Step 3: Install dependencies ---------------------------------------------
echo [3/6] Installing Python dependencies...
"%PYDIR%\python.exe" -m pip install --quiet --no-warn-script-location -r "%ROOT%\web\requirements.txt"
if errorlevel 1 ( echo ERROR: pip install failed. & exit /b 1 )
if exist "%PYDIR%\Scripts\pywin32_postinstall.py" (
    "%PYDIR%\python.exe" "%PYDIR%\Scripts\pywin32_postinstall.py" -install -quiet <nul >nul 2>nul
)
echo       Done.

:: -- Step 3b: Bundle portable Node.js (for npx/node MCP servers) --------------
:: Shipped in the app folder and preferred at runtime over any system Node, so
:: MCP servers work regardless of the user's Node install / PATH. Bump
:: NODE_VERSION to update. Windows is x64-only (matches the embedded Python).
echo [3b/6] Bundling Node.js runtime...
set NODE_VERSION=22.14.0
set NODE_ZIP=node-v%NODE_VERSION%-win-x64.zip
set NODE_URL=https://nodejs.org/dist/v%NODE_VERSION%/%NODE_ZIP%
set NODEDIR=%~dp0node_dist
if exist "%NODEDIR%\node.exe" (
    echo       Already present. Skipping download.
) else (
    echo       Downloading Node.js %NODE_VERSION%...
    if not exist "%~dp0%NODE_ZIP%" (
        curl -L -o "%~dp0%NODE_ZIP%" "%NODE_URL%"
        if errorlevel 1 ( echo ERROR: Node download failed. & exit /b 1 )
    )
    echo       Extracting...
    if exist "%~dp0node_tmp" rd /s /q "%~dp0node_tmp"
    powershell -Command "Expand-Archive -Path '%~dp0%NODE_ZIP%' -DestinationPath '%~dp0node_tmp' -Force"
    if errorlevel 1 ( echo ERROR: Node extraction failed. & exit /b 1 )
    md "%NODEDIR%" 2>nul
    rem Flatten the versioned top-level folder so node.exe lands at node_dist root.
    for /d %%d in ("%~dp0node_tmp\node-v*-win-x64") do robocopy "%%d" "%NODEDIR%" /E /NFL /NDL /NJH /NJS /NP >nul
    rd /s /q "%~dp0node_tmp"
    if not exist "%NODEDIR%\node.exe" ( echo ERROR: Node bundling failed. & exit /b 1 )
    echo       Done.
)

:: -- Step 4: Build tray launcher exe with PyInstaller -------------------------
echo [4/6] Building AIGator.exe launcher...
if exist "%BUILDDIR%\AIGator.exe" (
    echo       Already built. Skipping.
    goto :inno
)
"%PYDIR%\python.exe" -m PyInstaller ^
    --onefile ^
    --windowed ^
    --icon="%BUILDDIR%\aigator_icon.ico" ^
    --distpath="%BUILDDIR%" ^
    --workpath="%BUILDDIR%\pyinstaller_work" ^
    --specpath="%BUILDDIR%" ^
    --name=AIGator ^
    --collect-submodules=pystray ^
    --collect-submodules=PIL ^
    --noconfirm ^
    "%BUILDDIR%\..\tray\aigator_tray.py"
if errorlevel 1 ( echo ERROR: PyInstaller build failed. & exit /b 1 )
if exist "%BUILDDIR%\AIGator.spec" del /f "%BUILDDIR%\AIGator.spec"
if exist "%BUILDDIR%\pyinstaller_work" rd /s /q "%BUILDDIR%\pyinstaller_work"
echo       Done. AIGator.exe created.

:: -- Step 5: Bundle with Inno Setup -------------------------------------------
:inno
echo [5/6] Building installer with Inno Setup...
echo       ISCC found at: %ISCC%
if not defined ISCC (
    echo ERROR: Inno Setup 6 not found.
    echo        Download free from https://jrsoftware.org/isdl.php
    exit /b 1
)
powershell -Command "Stop-Process -Name AIGatorInstaller -Force -ErrorAction SilentlyContinue"
powershell -Command "Remove-Item '%BUILDDIR%\dist\AIGatorInstaller.exe' -Force -ErrorAction SilentlyContinue"
set /p APP_VERSION=<"%ROOT%\version.txt"
%ISCC% /DMyAppVersion=%APP_VERSION% "%~dp0installer.iss"
if errorlevel 1 ( echo ERROR: Inno Setup build failed. & exit /b 1 )

:: -- Step 6: Code signing -----------------------------------------------------
echo [6/6] Signing executables...
if not exist "%PFX_FILE%" (
    echo       WARNING: %PFX_FILE% not found. Skipping signing.
    echo       To sign, place the .pfx file in build\ and set AIGATOR_SIGN_PASSWORD.
    goto :build_done
)
if not defined SIGNTOOL (
    echo       WARNING: signtool.exe not found. Install Windows SDK to enable signing.
    goto :build_done
)
if not defined PFX_PASSWORD (
    echo.
    echo       Code-signing cert found, but AIGATOR_SIGN_PASSWORD is not set.
    set /p PFX_PASSWORD="      Enter PFX password (or press Enter to skip signing): "
)
if not defined PFX_PASSWORD (
    echo       Skipping signing — no password entered.
    goto :build_done
)
:: Disable delayed expansion so "!" in the password survives expansion.
:: Re-read from the env var inside this scope; the outer PFX_PASSWORD may
:: have lost "!" characters when the env var was first expanded.
setlocal DisableDelayedExpansion
if defined AIGATOR_SIGN_PASSWORD set "PFX_PASSWORD=%AIGATOR_SIGN_PASSWORD%"
if exist "%BUILDDIR%\AIGator.exe" (
    echo       Signing AIGator.exe...
    %SIGNTOOL% sign /f "%PFX_FILE%" /p "%PFX_PASSWORD%" /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 "%BUILDDIR%\AIGator.exe"
    if errorlevel 1 echo       WARNING: Signing AIGator.exe failed.
)
if exist "%BUILDDIR%\dist\AIGatorInstaller.exe" (
    echo       Signing AIGatorInstaller.exe...
    %SIGNTOOL% sign /f "%PFX_FILE%" /p "%PFX_PASSWORD%" /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 "%BUILDDIR%\dist\AIGatorInstaller.exe"
    if errorlevel 1 echo       WARNING: Signing AIGatorInstaller.exe failed.
)
endlocal
echo       Done.

:build_done
echo.
echo  ======================================
echo   Build complete!
echo   Launcher:  build\AIGator.exe
echo   Installer: build\dist\AIGatorInstaller.exe
echo  ======================================
echo.
exit /b 0
