# +==========================================================================+
# |  Uninstall-AIGator - removes the source/pip-track install of AI Gator.     |
# |                                                                            |
# |  Two stages, because Windows locks the folder a running process lives in:  |
# |    Stage 1 (runs from the install dir): confirm, stop gator, remove        |
# |             shortcuts, then copy itself to %TEMP% and relaunch as stage 2. |
# |    Stage 2 (runs from %TEMP%):          wait for handles to release, then  |
# |             delete the install dir (and, if asked, settings + history).    |
# |                                                                            |
# |  Launched by the tray "Uninstall AI Gator..." item and the Start-menu      |
# |  "Uninstall AI Gator" shortcut. Both just run stage 1.                     |
# +==========================================================================+
param(
    [string]$InstallDir = $PSScriptRoot,
    [switch]$Stage2,
    [switch]$RemoveData
)

$ErrorActionPreference = "SilentlyContinue"
Add-Type -AssemblyName System.Windows.Forms | Out-Null

function Stop-Gator {
    # Identity sweep: stop any process whose command line invokes a gator entry
    # point, on any port. Mirrors tray/aigator_tray.py _kill_gator_instances.
    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -match 'aigator_tray\.py|watchdog\.py|web\.app:app' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    # Port backstop: anything still listening on the default ports.
    foreach ($port in 8000, 8001) {
        Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    }
    Start-Sleep -Seconds 1
}

function Remove-Shortcuts {
    $targets = @(
        (Join-Path ([Environment]::GetFolderPath('Programs')) "AI Gator.lnk"),
        (Join-Path ([Environment]::GetFolderPath('Programs')) "Uninstall AI Gator.lnk"),
        (Join-Path ([Environment]::GetFolderPath('Desktop'))  "AI Gator.lnk"),
        (Join-Path ([Environment]::GetFolderPath('Startup'))  "AI Gator.lnk")
    )
    foreach ($t in $targets) { Remove-Item -LiteralPath $t -Force -ErrorAction SilentlyContinue }
}

function Remove-DataDirs {
    $dirs = @(
        (Join-Path $env:USERPROFILE ".gator"),
        (Join-Path $env:APPDATA "AIGator"),
        (Join-Path $env:LOCALAPPDATA "AIGator"),
        (Join-Path $env:USERPROFILE ".config\teamspoc")
    )
    foreach ($d in $dirs) { Remove-Item -LiteralPath $d -Recurse -Force -ErrorAction SilentlyContinue }
}

# ============================ STAGE 2 (from %TEMP%) ============================
if ($Stage2) {
    # Retry: pythonw can take a moment to release its DLL handles after Stop-Process.
    for ($i = 0; $i -lt 20; $i++) {
        Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
        if (-not (Test-Path -LiteralPath $InstallDir)) { break }
        Start-Sleep -Milliseconds 500
    }
    if ($RemoveData) { Remove-DataDirs }

    $gone = -not (Test-Path -LiteralPath $InstallDir)
    if ($gone) {
        [System.Windows.Forms.MessageBox]::Show(
            "AI Gator has been uninstalled.",
            "AI Gator", 'OK', 'Information') | Out-Null
    } else {
        [System.Windows.Forms.MessageBox]::Show(
            "Could not fully remove:`n$InstallDir`n`nClose any open AI Gator windows and delete that folder manually.",
            "AI Gator", 'OK', 'Warning') | Out-Null
    }
    # Best-effort self-delete of this temp copy after we exit.
    Start-Process cmd.exe -WindowStyle Hidden -ArgumentList `
        "/c timeout /t 2 >nul & del /f /q `"$PSCommandPath`"" | Out-Null
    return
}

# ============================ STAGE 1 (from install dir) =======================
$confirm = [System.Windows.Forms.MessageBox]::Show(
    "Uninstall AI Gator?`n`nThis stops the gator and removes the app from:`n$InstallDir",
    "Uninstall AI Gator", 'YesNo', 'Question')
if ($confirm -ne 'Yes') { return }

# Shared with the .exe installer track, so default to KEEPING settings + history.
$dataAns = [System.Windows.Forms.MessageBox]::Show(
    "Also remove your settings and history?`n`n" +
    "Yes  - delete config, tasks, schedules, and logs (full clean)`n" +
    "No   - keep them (recommended if you might reinstall)",
    "Remove your data?", 'YesNo', 'Question')
$removeData = ($dataAns -eq 'Yes')

Stop-Gator
Remove-Shortcuts

# Hand off to stage 2 from a copy outside the install dir, so it can delete this
# folder without the script file (or our own process) locking it.
$stage2 = Join-Path $env:TEMP ("Uninstall-AIGator-" + [Guid]::NewGuid().ToString("N") + ".ps1")
Copy-Item -LiteralPath $PSCommandPath -Destination $stage2 -Force

$argList = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
    "-File", "`"$stage2`"",
    "-InstallDir", "`"$InstallDir`"",
    "-Stage2"
)
if ($removeData) { $argList += "-RemoveData" }
Start-Process powershell.exe -ArgumentList $argList | Out-Null
