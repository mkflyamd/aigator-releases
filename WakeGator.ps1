# +==========================================================================+
# |  WakeGator - AI Gator one-command setup for alpha testers                  |
# |  Installs dependencies, wires up Start Menu / tray, and wakes the gator.   |
# |  Usage:  right-click -> Run with PowerShell                                 |
# |     or:  powershell -ExecutionPolicy Bypass -File WakeGator.ps1            |
# +==========================================================================+

$ErrorActionPreference = "Stop"
$projectDir = $PSScriptRoot
$ProgressPreference = "SilentlyContinue"   # speeds up Invoke-WebRequest / winget UI

# -- Look & feel helpers -------------------------------------------------------
function Write-Gator {
    param([string]$Text, [string]$Color = "White")
    Write-Host $Text -ForegroundColor $Color
}
function Write-Step {
    param([int]$Num, [int]$Total, [string]$Text)
    Write-Host ""
    Write-Host "  [$Num/$Total] " -ForegroundColor DarkGray -NoNewline
    Write-Host $Text -ForegroundColor Cyan
}
function Write-OK   { param([string]$Text) Write-Host "      " -NoNewline; Write-Host "OK " -ForegroundColor Green -NoNewline; Write-Host $Text -ForegroundColor Gray }
function Write-Info { param([string]$Text) Write-Host "      -> $Text" -ForegroundColor DarkGray }
function Write-Warn { param([string]$Text) Write-Host "      ! $Text" -ForegroundColor Yellow }
function Write-Err  { param([string]$Text) Write-Host "      x $Text" -ForegroundColor Red }
function Ask-YesNo {
    param([string]$Question, [bool]$Default = $true)
    $hint = if ($Default) { "[Y/n]" } else { "[y/N]" }
    Write-Host "      $Question $hint " -ForegroundColor White -NoNewline
    $ans = Read-Host
    if ([string]::IsNullOrWhiteSpace($ans)) { return $Default }
    return $ans -match '^(y|yes)$'
}
# Runs $Exe with $Args while showing a live spinner + elapsed time, so long
# steps (like the first pip install) don't look frozen. Returns $true on success.
function Invoke-WithProgress {
    param([string]$Exe, [string]$Label, [string[]]$CmdArgs)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe
    $psi.Arguments = (($CmdArgs | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' ')
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $psi
    # Drain both pipes asynchronously so a chatty child (pip download progress)
    # can't fill the buffer and deadlock while we animate the spinner.
    $sink = { $null = $EventArgs.Data }
    $oe = Register-ObjectEvent -InputObject $p -EventName OutputDataReceived -Action $sink
    $ee = Register-ObjectEvent -InputObject $p -EventName ErrorDataReceived -Action $sink
    [void]$p.Start()
    $p.BeginOutputReadLine()
    $p.BeginErrorReadLine()
    $spin = '|', '/', '-', '\'
    $i = 0
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while (-not $p.HasExited) {
        $i++
        $line = "      {0} {1}  [{2}s]" -f $spin[$i % 4], $Label, [int]$sw.Elapsed.TotalSeconds
        Write-Host ("`r" + $line.PadRight(78)) -ForegroundColor DarkGray -NoNewline
        Start-Sleep -Milliseconds 150
    }
    $sw.Stop()
    $p.WaitForExit()
    $code = $p.ExitCode
    Unregister-Event -SourceIdentifier $oe.Name -ErrorAction SilentlyContinue
    Unregister-Event -SourceIdentifier $ee.Name -ErrorAction SilentlyContinue
    Write-Host ("`r" + (" " * 78) + "`r") -NoNewline
    return ($code -eq 0)
}

# -- Banner --------------------------------------------------------------------
$version = (Get-Content (Join-Path $projectDir "version.txt") -ErrorAction SilentlyContinue) -join ""
Clear-Host
Write-Host ""
Write-Gator "        .-._   _ _ _ _ _ _ _ _" "Green"
Write-Gator "  .-''-.__.-'00  '-' ' ' ' ' ' '-." "Green"
Write-Gator " '.___ '    .   .--_'-' '-' '-' _'-' '._" "Green"
Write-Gator "  V: V 'vv-'   '_   '.       .'  _..' '.'." "DarkGreen"
Write-Gator "    '=.____.=_.--'   :_.__.__:_   '.   : :" "DarkGreen"
Write-Gator "            (((____.-'        '-.  /   : :" "DarkGreen"
Write-Host ""
Write-Gator "                A I   G A T O R" "Green"
if ($version) { Write-Gator "                  v$version  -  Waking up..." "DarkGray" }
Write-Host ""
Write-Gator "  ============================================================" "DarkGray"

$TOTAL = 6

# -- Step 1: Python 3.12 -------------------------------------------------------
Write-Step 1 $TOTAL "Checking for Python 3.12"
# Finds a real Python 3.12+ and returns its concrete interpreter path. The
# Microsoft Store build (and its app-execution-alias stub under \WindowsApps\)
# is deliberately rejected: its AppX sandbox redirects AppData\Local writes into
# a private LocalCache, so the tray, watchdog, and browser each see different
# lock/log/PID files and the server never comes up. Prefer the py launcher and
# the well-known python.org install locations instead.
function Get-Python312 {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) { $candidates += , @("py", "-3.12") }
    foreach ($c in (Get-Command python -All -ErrorAction SilentlyContinue)) { $candidates += , @($c.Source) }
    foreach ($p in @(
            "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
            "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
            "$env:ProgramFiles\Python312\python.exe",
            "$env:ProgramFiles\Python313\python.exe"
        )) { if (Test-Path $p) { $candidates += , @($p) } }

    foreach ($cand in $candidates) {
        $exe = $cand[0]
        $probe = if ($cand.Count -gt 1) { $cand[1..($cand.Count - 1)] } else { @() }
        try {
            # Resolve to the true interpreter path so PATH stubs / the py launcher
            # don't hide a Store build.
            $real = & $exe @probe -c "import sys; print(sys.executable)" 2>$null
            if (-not $real) { continue }
            $real = ($real | Select-Object -First 1).Trim()
            if ($real -match '\\WindowsApps\\') { continue }   # skip the sandboxed Store build
            $ver = & $real --version 2>&1
            if ($ver -match "Python 3\.(1[2-9]|[2-9][0-9])") { return $real }
        } catch { }
    }
    return $null
}
$pyCmd = Get-Python312
if (-not $pyCmd) {
    Write-Warn "No suitable Python 3.12+ found."
    Write-Info "(A Microsoft Store Python, if present, is skipped - its sandbox breaks the app.)"
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        if (Ask-YesNo "Install Python 3.12 now with winget?") {
            Write-Info "Installing Python 3.12 (this may take a minute)..."
            winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
            $pyCmd = Get-Python312   # re-probe; winget --scope user lands in a path we check
        }
    }
}
if (-not $pyCmd) {
    Write-Err "Install Python 3.12 from https://www.python.org/downloads/ (tick 'Add to PATH'),"
    Write-Err "then run WakeGator again."
    Read-Host "      Press Enter to exit"
    exit 1
}
$pyVer = & $pyCmd --version 2>&1
Write-OK "Found $pyVer"

# -- Bundle Node.js (portable, for npx/node MCP servers) -----------------------
# AI Gator ships its own portable Node in the app folder and prefers it at runtime
# over any system Node (see web/proc_utils.py:ensure_bundled_node_on_path). This
# makes npx/node MCP servers work regardless of the user's Node install/PATH.
# Non-fatal: if the download fails, the app still starts (just no npx/node MCP).
$nodeVersion = "22.14.0"
$nodeDir = Join-Path $projectDir "node"
$nodeExe = Join-Path $nodeDir "node.exe"
if (Test-Path $nodeExe) {
    Write-OK "Node.js runtime already present."
} else {
    Write-Info "Setting up Node.js runtime (for npx/node MCP servers)..."
    try {
        $nodeZipName = "node-v$nodeVersion-win-x64"
        $nodeUrl = "https://nodejs.org/dist/v$nodeVersion/$nodeZipName.zip"
        $tmpZip = Join-Path $env:TEMP "$nodeZipName.zip"
        $tmpEx  = Join-Path $env:TEMP "aigator_node_tmp"
        if (Test-Path $tmpEx) { Remove-Item $tmpEx -Recurse -Force -ErrorAction SilentlyContinue }
        Invoke-WebRequest -Uri $nodeUrl -OutFile $tmpZip -UseBasicParsing
        Expand-Archive -Path $tmpZip -DestinationPath $tmpEx -Force
        # Flatten the versioned top-level folder so node.exe lands at node\ root.
        $inner = Join-Path $tmpEx $nodeZipName
        if (Test-Path $inner) {
            New-Item -ItemType Directory -Force -Path $nodeDir | Out-Null
            Copy-Item -Path (Join-Path $inner '*') -Destination $nodeDir -Recurse -Force
        }
        Remove-Item $tmpZip -Force -ErrorAction SilentlyContinue
        Remove-Item $tmpEx -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path $nodeExe) { Write-OK "Node.js $nodeVersion ready." }
        else { Write-Warn "Node.js setup didn't complete - npx/node MCP servers may not work." }
    } catch {
        Write-Warn "Could not set up Node.js: $($_.Exception.Message)"
        Write-Info "npx/node-based MCP servers may not work until Node is installed."
    }
}

# -- Step 2: Virtual environment -----------------------------------------------
Write-Step 2 $TOTAL "Setting up an isolated environment"
$venvDir = Join-Path $projectDir ".venv"
$venvPy  = Join-Path $venvDir "Scripts\python.exe"
$venvPyw = Join-Path $venvDir "Scripts\pythonw.exe"
# A venv previously built from the sandboxed Microsoft Store Python is poisoned
# (its AppData writes get redirected, so the tray/watchdog never line up) and is
# reused on every re-run unless we tear it down. Detect it via pyvenv.cfg and
# rebuild from the real interpreter we just resolved.
$venvCfg = Join-Path $venvDir "pyvenv.cfg"
if ((Test-Path $venvCfg) -and ((Get-Content $venvCfg -Raw) -match 'WindowsApps')) {
    Write-Warn "Existing environment was built from Microsoft Store Python - rebuilding it."
    Remove-Item $venvDir -Recurse -Force -ErrorAction SilentlyContinue
}
if (Test-Path $venvPy) {
    Write-OK "Environment already exists - reusing it."
} else {
    Write-Info "Creating .venv ..."
    & $pyCmd -m venv $venvDir
    if (-not (Test-Path $venvPy)) { Write-Err "Failed to create virtual environment."; Read-Host "      Press Enter to exit"; exit 1 }
    Write-OK "Environment created."
}

# -- Step 3: Dependencies ------------------------------------------------------
Write-Step 3 $TOTAL "Installing dependencies (a few minutes the first time)"
if (-not (Invoke-WithProgress $venvPy "Upgrading pip" @("-m", "pip", "install", "--upgrade", "pip", "--quiet"))) {
    Write-Warn "pip upgrade hit a snag - continuing anyway."
}
$reqFile = Join-Path $projectDir "requirements.txt"
if (-not (Invoke-WithProgress $venvPy "Installing packages (first run downloads a lot - hang tight)" @("-m", "pip", "install", "-r", $reqFile, "--quiet"))) {
    Write-Err "Dependency install failed. If you're on a corporate network, a proxy may be blocking pip."
    Read-Host "      Press Enter to exit"; exit 1
}
Write-OK "Dependencies installed."

# -- Step 4: Windows integration (pywin32) -------------------------------------
Write-Step 4 $TOTAL "Finishing Windows integration"
$postInstall = Join-Path $venvDir "Scripts\pywin32_postinstall.py"
if (Test-Path $postInstall) {
    & $venvPy $postInstall -install -quiet | Out-Null
    Write-OK "System tray + Office integration ready."
} else {
    Write-Info "pywin32 post-install not needed."
}

# -- Step 5: Shortcuts (make it feel like an installed app) ---------------------
Write-Step 5 $TOTAL "Adding shortcuts"
$trayScript = Join-Path $projectDir "tray\aigator_tray.py"
$icon       = Join-Path $projectDir "build\aigator_icon.ico"
function New-Shortcut {
    param([string]$Path)
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($Path)
    $sc.TargetPath       = $venvPyw
    $sc.Arguments        = "`"$trayScript`""
    $sc.WorkingDirectory = $projectDir
    if (Test-Path $icon) { $sc.IconLocation = $icon }
    $sc.Description      = "AI Gator"
    $sc.Save()
}
# Start Menu - always, so it shows in the Windows apps list like the installer does
$startMenu = [Environment]::GetFolderPath('Programs')
New-Shortcut (Join-Path $startMenu "AI Gator.lnk")
Write-OK "Added to Start Menu (search 'AI Gator')."
# Uninstall entry in the Start Menu, mirroring the .exe installer's Add/Remove entry.
$uninstallScript = Join-Path $projectDir "Uninstall-AIGator.ps1"
if (Test-Path $uninstallScript) {
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut((Join-Path $startMenu "Uninstall AI Gator.lnk"))
    $sc.TargetPath       = "powershell.exe"
    $sc.Arguments        = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$uninstallScript`""
    $sc.WorkingDirectory = $projectDir
    if (Test-Path $icon) { $sc.IconLocation = $icon }
    $sc.Description      = "Uninstall AI Gator"
    $sc.Save()
    Write-OK "Added 'Uninstall AI Gator' to Start Menu."
}
# Desktop - optional
if (Ask-YesNo "Add a desktop shortcut?") {
    New-Shortcut (Join-Path ([Environment]::GetFolderPath('Desktop')) "AI Gator.lnk")
    Write-OK "Desktop shortcut added."
}
# Startup - optional auto-launch on login (matches the exe installer)
if (Ask-YesNo "Launch AI Gator automatically when you log in?") {
    New-Shortcut (Join-Path ([Environment]::GetFolderPath('Startup')) "AI Gator.lnk")
    Write-OK "Will start automatically on login."
}

# -- Step 6: Wake the gator ----------------------------------------------------
Write-Step 6 $TOTAL "Waking the gator"
Start-Process $venvPyw -ArgumentList "`"$trayScript`"" -WorkingDirectory $projectDir
Write-OK "AI Gator is starting in your system tray."

# -- Done ----------------------------------------------------------------------
Write-Host ""
Write-Gator "  ============================================================" "DarkGray"
Write-Host ""
Write-Gator "   The gator is awake!  Chomp chomp." "Green"
Write-Host ""
Write-Info  "Your browser will open at http://localhost:8000 shortly."
Write-Info  "Look for the gator icon in your system tray (bottom-right)."
Write-Host ""
Write-Gator "   To open it again later:" "White"
Write-Info  "Start Menu  ->  search 'AI Gator'   (or the desktop icon)"
Write-Host ""
Read-Host "      Press Enter to close this window"

# SIG # Begin signature block
# MIIb4QYJKoZIhvcNAQcCoIIb0jCCG84CAQExDzANBglghkgBZQMEAgEFADB5Bgor
# BgEEAYI3AgEEoGswaTA0BgorBgEEAYI3AgEeMCYCAwEAAAQQH8w7YFlLCE63JNLG
# KX7zUQIBAAIBAAIBAAIBAAIBADAxMA0GCWCGSAFlAwQCAQUABCCZ2HeDWjGz2y3E
# Pwm4uUbYE/SVwTOm+HkbB7pVC3X0l6CCFjQwggL2MIIB3qADAgECAhAs3HQ5t3xL
# vkQUR0DfYsvOMA0GCSqGSIb3DQEBCwUAMBMxETAPBgNVBAMMCEdhdG9yLkFJMB4X
# DTI2MDUyMDA4MTUzNloXDTI5MDUyMDA4MjUzNVowEzERMA8GA1UEAwwIR2F0b3Iu
# QUkwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQC3T4f+PT8jaLGIvqb5
# O2cnhjDUDR05ceMJDlFyGUEw1k3kCfXCPqnrTHglBzWVd5Jzt8aqv7w89bpqiq8h
# ZmM7lBcX7a9mHoTl+u+DHfya3zK5rUuCj8wTXT7UmgLkk2BpRj7iS6cD1rgQ+Jpg
# 2nyXvETq9C9M/e1qKV2e5Kwu/kJTEtudn9p2mEPOjh3vRZHNOfIZvNudLxnOBzp4
# Xu58cEn2162H1u8B/X4efJYWzdwqHqbk6vXpv3e8B3B2jrMxAO+QasuEb1DzX0Tr
# Qxrja0gifccPqop0XxS38p1kzgewRHP24e/+/0APlFiDuZp6GDbXDB3ibWu8L4YH
# rmL1AgMBAAGjRjBEMA4GA1UdDwEB/wQEAwIHgDATBgNVHSUEDDAKBggrBgEFBQcD
# AzAdBgNVHQ4EFgQUHs97MpvAjxCUUQboLWSBuOFzoeswDQYJKoZIhvcNAQELBQAD
# ggEBAAYJQUkqzbZzL+WUzGkeUO/Bn3XhO8z1HXrI3sh0rbWKt3OVOSucS4Y/6ba5
# PWnDvyMS9BsFhjtQuXKcoW0UoaTXOGWskjQdniv+12RjbAnA2M+WuFHcIsF706N+
# rll3sRAwXEkB/wG0+qRjbplZsquYWRUaUbFCRjQXsyFtYcAVxpMy8Pbe6o79Y/oy
# K67dEotOIqmlcvHMWQCHFmFdEPFmaKDedghH6frvGOKprBOX9XsaIL4YpiKWJRHc
# 2pZpVnFDme9dHkbBW7Z0ilnD9oQZa5AGEB5NCc8961pBm78HU1zlnADz5QRKBwtF
# j20BIct9t0S3XUIovCYUEXRyz8AwggWNMIIEdaADAgECAhAOmxiO+dAt5+/bUOII
# QBhaMA0GCSqGSIb3DQEBDAUAMGUxCzAJBgNVBAYTAlVTMRUwEwYDVQQKEwxEaWdp
# Q2VydCBJbmMxGTAXBgNVBAsTEHd3dy5kaWdpY2VydC5jb20xJDAiBgNVBAMTG0Rp
# Z2lDZXJ0IEFzc3VyZWQgSUQgUm9vdCBDQTAeFw0yMjA4MDEwMDAwMDBaFw0zMTEx
# MDkyMzU5NTlaMGIxCzAJBgNVBAYTAlVTMRUwEwYDVQQKEwxEaWdpQ2VydCBJbmMx
# GTAXBgNVBAsTEHd3dy5kaWdpY2VydC5jb20xITAfBgNVBAMTGERpZ2lDZXJ0IFRy
# dXN0ZWQgUm9vdCBHNDCCAiIwDQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIBAL/m
# kHNo3rvkXUo8MCIwaTPswqclLskhPfKK2FnC4SmnPVirdprNrnsbhA3EMB/zG6Q4
# FutWxpdtHauyefLKEdLkX9YFPFIPUh/GnhWlfr6fqVcWWVVyr2iTcMKyunWZanMy
# lNEQRBAu34LzB4TmdDttceItDBvuINXJIB1jKS3O7F5OyJP4IWGbNOsFxl7sWxq8
# 68nPzaw0QF+xembud8hIqGZXV59UWI4MK7dPpzDZVu7Ke13jrclPXuU15zHL2pNe
# 3I6PgNq2kZhAkHnDeMe2scS1ahg4AxCN2NQ3pC4FfYj1gj4QkXCrVYJBMtfbBHMq
# bpEBfCFM1LyuGwN1XXhm2ToxRJozQL8I11pJpMLmqaBn3aQnvKFPObURWBf3JFxG
# j2T3wWmIdph2PVldQnaHiZdpekjw4KISG2aadMreSx7nDmOu5tTvkpI6nj3cAORF
# JYm2mkQZK37AlLTSYW3rM9nF30sEAMx9HJXDj/chsrIRt7t/8tWMcCxBYKqxYxhE
# lRp2Yn72gLD76GSmM9GJB+G9t+ZDpBi4pncB4Q+UDCEdslQpJYls5Q5SUUd0vias
# tkF13nqsX40/ybzTQRESW+UQUOsxxcpyFiIJ33xMdT9j7CFfxCBRa2+xq4aLT8LW
# RV+dIPyhHsXAj6KxfgommfXkaS+YHS312amyHeUbAgMBAAGjggE6MIIBNjAPBgNV
# HRMBAf8EBTADAQH/MB0GA1UdDgQWBBTs1+OC0nFdZEzfLmc/57qYrhwPTzAfBgNV
# HSMEGDAWgBRF66Kv9JLLgjEtUYunpyGd823IDzAOBgNVHQ8BAf8EBAMCAYYweQYI
# KwYBBQUHAQEEbTBrMCQGCCsGAQUFBzABhhhodHRwOi8vb2NzcC5kaWdpY2VydC5j
# b20wQwYIKwYBBQUHMAKGN2h0dHA6Ly9jYWNlcnRzLmRpZ2ljZXJ0LmNvbS9EaWdp
# Q2VydEFzc3VyZWRJRFJvb3RDQS5jcnQwRQYDVR0fBD4wPDA6oDigNoY0aHR0cDov
# L2NybDMuZGlnaWNlcnQuY29tL0RpZ2lDZXJ0QXNzdXJlZElEUm9vdENBLmNybDAR
# BgNVHSAECjAIMAYGBFUdIAAwDQYJKoZIhvcNAQEMBQADggEBAHCgv0NcVec4X6Cj
# dBs9thbX979XB72arKGHLOyFXqkauyL4hxppVCLtpIh3bb0aFPQTSnovLbc47/T/
# gLn4offyct4kvFIDyE7QKt76LVbP+fT3rDB6mouyXtTP0UNEm0Mh65ZyoUi0mcud
# T6cGAxN3J0TU53/oWajwvy8LpunyNDzs9wPHh6jSTEAZNUZqaVSwuKFWjuyk1T3o
# sdz9HNj0d1pcVIxv76FQPfx2CWiEn2/K2yCNNWAcAgPLILCsWKAOQGPFmCLBsln1
# VWvPJ6tsds5vIy30fnFqI2si/xK4VC0nftg62fC2h5b9W9FcrBjDTZ9ztwGpn1eq
# XijiuZQwgga0MIIEnKADAgECAhANx6xXBf8hmS5AQyIMOkmGMA0GCSqGSIb3DQEB
# CwUAMGIxCzAJBgNVBAYTAlVTMRUwEwYDVQQKEwxEaWdpQ2VydCBJbmMxGTAXBgNV
# BAsTEHd3dy5kaWdpY2VydC5jb20xITAfBgNVBAMTGERpZ2lDZXJ0IFRydXN0ZWQg
# Um9vdCBHNDAeFw0yNTA1MDcwMDAwMDBaFw0zODAxMTQyMzU5NTlaMGkxCzAJBgNV
# BAYTAlVTMRcwFQYDVQQKEw5EaWdpQ2VydCwgSW5jLjFBMD8GA1UEAxM4RGlnaUNl
# cnQgVHJ1c3RlZCBHNCBUaW1lU3RhbXBpbmcgUlNBNDA5NiBTSEEyNTYgMjAyNSBD
# QTEwggIiMA0GCSqGSIb3DQEBAQUAA4ICDwAwggIKAoICAQC0eDHTCphBcr48RsAc
# rHXbo0ZodLRRF51NrY0NlLWZloMsVO1DahGPNRcybEKq+RuwOnPhof6pvF4uGjwj
# qNjfEvUi6wuim5bap+0lgloM2zX4kftn5B1IpYzTqpyFQ/4Bt0mAxAHeHYNnQxqX
# mRinvuNgxVBdJkf77S2uPoCj7GH8BLuxBG5AvftBdsOECS1UkxBvMgEdgkFiDNYi
# OTx4OtiFcMSkqTtF2hfQz3zQSku2Ws3IfDReb6e3mmdglTcaarps0wjUjsZvkgFk
# riK9tUKJm/s80FiocSk1VYLZlDwFt+cVFBURJg6zMUjZa/zbCclF83bRVFLeGkuA
# hHiGPMvSGmhgaTzVyhYn4p0+8y9oHRaQT/aofEnS5xLrfxnGpTXiUOeSLsJygoLP
# p66bkDX1ZlAeSpQl92QOMeRxykvq6gbylsXQskBBBnGy3tW/AMOMCZIVNSaz7BX8
# VtYGqLt9MmeOreGPRdtBx3yGOP+rx3rKWDEJlIqLXvJWnY0v5ydPpOjL6s36czwz
# sucuoKs7Yk/ehb//Wx+5kMqIMRvUBDx6z1ev+7psNOdgJMoiwOrUG2ZdSoQbU2rM
# kpLiQ6bGRinZbI4OLu9BMIFm1UUl9VnePs6BaaeEWvjJSjNm2qA+sdFUeEY0qVjP
# KOWug/G6X5uAiynM7Bu2ayBjUwIDAQABo4IBXTCCAVkwEgYDVR0TAQH/BAgwBgEB
# /wIBADAdBgNVHQ4EFgQU729TSunkBnx6yuKQVvYv1Ensy04wHwYDVR0jBBgwFoAU
# 7NfjgtJxXWRM3y5nP+e6mK4cD08wDgYDVR0PAQH/BAQDAgGGMBMGA1UdJQQMMAoG
# CCsGAQUFBwMIMHcGCCsGAQUFBwEBBGswaTAkBggrBgEFBQcwAYYYaHR0cDovL29j
# c3AuZGlnaWNlcnQuY29tMEEGCCsGAQUFBzAChjVodHRwOi8vY2FjZXJ0cy5kaWdp
# Y2VydC5jb20vRGlnaUNlcnRUcnVzdGVkUm9vdEc0LmNydDBDBgNVHR8EPDA6MDig
# NqA0hjJodHRwOi8vY3JsMy5kaWdpY2VydC5jb20vRGlnaUNlcnRUcnVzdGVkUm9v
# dEc0LmNybDAgBgNVHSAEGTAXMAgGBmeBDAEEAjALBglghkgBhv1sBwEwDQYJKoZI
# hvcNAQELBQADggIBABfO+xaAHP4HPRF2cTC9vgvItTSmf83Qh8WIGjB/T8ObXAZz
# 8OjuhUxjaaFdleMM0lBryPTQM2qEJPe36zwbSI/mS83afsl3YTj+IQhQE7jU/kXj
# jytJgnn0hvrV6hqWGd3rLAUt6vJy9lMDPjTLxLgXf9r5nWMQwr8Myb9rEVKChHyf
# pzee5kH0F8HABBgr0UdqirZ7bowe9Vj2AIMD8liyrukZ2iA/wdG2th9y1IsA0QF8
# dTXqvcnTmpfeQh35k5zOCPmSNq1UH410ANVko43+Cdmu4y81hjajV/gxdEkMx1NK
# U4uHQcKfZxAvBAKqMVuqte69M9J6A47OvgRaPs+2ykgcGV00TYr2Lr3ty9qIijan
# rUR3anzEwlvzZiiyfTPjLbnFRsjsYg39OlV8cipDoq7+qNNjqFzeGxcytL5TTLL4
# ZaoBdqbhOhZ3ZRDUphPvSRmMThi0vw9vODRzW6AxnJll38F0cuJG7uEBYTptMSbh
# dhGQDpOXgpIUsWTjd6xpR6oaQf/DJbg3s6KCLPAlZ66RzIg9sC+NJpud/v4+7RWs
# WCiKi9EOLLHfMR2ZyJ/+xhCx9yHbxtl5TPau1j/1MIDpMPx0LckTetiSuEtQvLsN
# z3Qbp7wGWqbIiOWCnb5WqxL3/BAPvIXKUjPSxyZsq8WhbaM2tszWkPZPubdcMIIG
# 7TCCBNWgAwIBAgIQCoDvGEuN8QWC0cR2p5V0aDANBgkqhkiG9w0BAQsFADBpMQsw
# CQYDVQQGEwJVUzEXMBUGA1UEChMORGlnaUNlcnQsIEluYy4xQTA/BgNVBAMTOERp
# Z2lDZXJ0IFRydXN0ZWQgRzQgVGltZVN0YW1waW5nIFJTQTQwOTYgU0hBMjU2IDIw
# MjUgQ0ExMB4XDTI1MDYwNDAwMDAwMFoXDTM2MDkwMzIzNTk1OVowYzELMAkGA1UE
# BhMCVVMxFzAVBgNVBAoTDkRpZ2lDZXJ0LCBJbmMuMTswOQYDVQQDEzJEaWdpQ2Vy
# dCBTSEEyNTYgUlNBNDA5NiBUaW1lc3RhbXAgUmVzcG9uZGVyIDIwMjUgMTCCAiIw
# DQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIBANBGrC0Sxp7Q6q5gVrMrV7pvUf+G
# cAoB38o3zBlCMGMyqJnfFNZx+wvA69HFTBdwbHwBSOeLpvPnZ8ZN+vo8dE2/pPvO
# x/Vj8TchTySA2R4QKpVD7dvNZh6wW2R6kSu9RJt/4QhguSssp3qome7MrxVyfQO9
# sMx6ZAWjFDYOzDi8SOhPUWlLnh00Cll8pjrUcCV3K3E0zz09ldQ//nBZZREr4h/G
# I6Dxb2UoyrN0ijtUDVHRXdmncOOMA3CoB/iUSROUINDT98oksouTMYFOnHoRh6+8
# 6Ltc5zjPKHW5KqCvpSduSwhwUmotuQhcg9tw2YD3w6ySSSu+3qU8DD+nigNJFmt6
# LAHvH3KSuNLoZLc1Hf2JNMVL4Q1OpbybpMe46YceNA0LfNsnqcnpJeItK/DhKbPx
# TTuGoX7wJNdoRORVbPR1VVnDuSeHVZlc4seAO+6d2sC26/PQPdP51ho1zBp+xUIZ
# kpSFA8vWdoUoHLWnqWU3dCCyFG1roSrgHjSHlq8xymLnjCbSLZ49kPmk8iyyizND
# IXj//cOgrY7rlRyTlaCCfw7aSUROwnu7zER6EaJ+AliL7ojTdS5PWPsWeupWs7Np
# ChUk555K096V1hE0yZIXe+giAwW00aHzrDchIc2bQhpp0IoKRR7YufAkprxMiXAJ
# Q1XCmnCfgPf8+3mnAgMBAAGjggGVMIIBkTAMBgNVHRMBAf8EAjAAMB0GA1UdDgQW
# BBTkO/zyMe39/dfzkXFjGVBDz2GM6DAfBgNVHSMEGDAWgBTvb1NK6eQGfHrK4pBW
# 9i/USezLTjAOBgNVHQ8BAf8EBAMCB4AwFgYDVR0lAQH/BAwwCgYIKwYBBQUHAwgw
# gZUGCCsGAQUFBwEBBIGIMIGFMCQGCCsGAQUFBzABhhhodHRwOi8vb2NzcC5kaWdp
# Y2VydC5jb20wXQYIKwYBBQUHMAKGUWh0dHA6Ly9jYWNlcnRzLmRpZ2ljZXJ0LmNv
# bS9EaWdpQ2VydFRydXN0ZWRHNFRpbWVTdGFtcGluZ1JTQTQwOTZTSEEyNTYyMDI1
# Q0ExLmNydDBfBgNVHR8EWDBWMFSgUqBQhk5odHRwOi8vY3JsMy5kaWdpY2VydC5j
# b20vRGlnaUNlcnRUcnVzdGVkRzRUaW1lU3RhbXBpbmdSU0E0MDk2U0hBMjU2MjAy
# NUNBMS5jcmwwIAYDVR0gBBkwFzAIBgZngQwBBAIwCwYJYIZIAYb9bAcBMA0GCSqG
# SIb3DQEBCwUAA4ICAQBlKq3xHCcEua5gQezRCESeY0ByIfjk9iJP2zWLpQq1b4UR
# GnwWBdEZD9gBq9fNaNmFj6Eh8/YmRDfxT7C0k8FUFqNh+tshgb4O6Lgjg8K8elC4
# +oWCqnU/ML9lFfim8/9yJmZSe2F8AQ/UdKFOtj7YMTmqPO9mzskgiC3QYIUP2S3H
# QvHG1FDu+WUqW4daIqToXFE/JQ/EABgfZXLWU0ziTN6R3ygQBHMUBaB5bdrPbF6M
# RYs03h4obEMnxYOX8VBRKe1uNnzQVTeLni2nHkX/QqvXnNb+YkDFkxUGtMTaiLR9
# wjxUxu2hECZpqyU1d0IbX6Wq8/gVutDojBIFeRlqAcuEVT0cKsb+zJNEsuEB7O7/
# cuvTQasnM9AWcIQfVjnzrvwiCZ85EE8LUkqRhoS3Y50OHgaY7T/lwd6UArb+BOVA
# kg2oOvol/DJgddJ35XTxfUlQ+8Hggt8l2Yv7roancJIFcbojBcxlRcGG0LIhp6Gv
# ReQGgMgYxQbV1S3CrWqZzBt1R9xJgKf47CdxVRd/ndUlQ05oxYy2zRWVFjF7mcr4
# C34Mj3ocCVccAvlKV9jEnstrniLvUxxVZE/rptb7IRE2lskKPIJgbaP5t2nGj/UL
# Li49xTcBZU8atufk+EMF/cWuiC7POGT75qaL6vdCvHlshtjdNXOCIUjsarfNZzGC
# BQMwggT/AgEBMCcwEzERMA8GA1UEAwwIR2F0b3IuQUkCECzcdDm3fEu+RBRHQN9i
# y84wDQYJYIZIAWUDBAIBBQCggYQwGAYKKwYBBAGCNwIBDDEKMAigAoAAoQKAADAZ
# BgkqhkiG9w0BCQMxDAYKKwYBBAGCNwIBBDAcBgorBgEEAYI3AgELMQ4wDAYKKwYB
# BAGCNwIBFTAvBgkqhkiG9w0BCQQxIgQgavG3TO6lX10usiAKK6zQU8tR92ALno/b
# lflQBRsdvIowDQYJKoZIhvcNAQEBBQAEggEAF6268cIhR/2bXoB/jIUkqh7e8RvI
# fgkA7p0oFKmJr65SPsVL0VqhcrCXa0ham3JQAPcASdxMgrbqf1TkvhOGe6Hdhh9V
# Phe+db+pSX+VpuEvCLEM9ARq9L2rGwHrhLLmWD6NXSJpM8LFhOUiUE8Lx1jJfRFA
# WuX2Oq+b8igiHFqYVvdoptS9UOHUxO21zcmago1WIoCKcUbUdZT0VvX8LCVEaJal
# M9jokcKaOctQWIjOiHXNV5tg0qDzESOMso0LZFZagtNtwDhVrBSHpKx+0XK/ZpHl
# jM/J3v15M0XdSrBIBseoY8h70jekfkdAdzGkUZ4d+Ok0Tiiv9ckK0Mq6oaGCAyYw
# ggMiBgkqhkiG9w0BCQYxggMTMIIDDwIBATB9MGkxCzAJBgNVBAYTAlVTMRcwFQYD
# VQQKEw5EaWdpQ2VydCwgSW5jLjFBMD8GA1UEAxM4RGlnaUNlcnQgVHJ1c3RlZCBH
# NCBUaW1lU3RhbXBpbmcgUlNBNDA5NiBTSEEyNTYgMjAyNSBDQTECEAqA7xhLjfEF
# gtHEdqeVdGgwDQYJYIZIAWUDBAIBBQCgaTAYBgkqhkiG9w0BCQMxCwYJKoZIhvcN
# AQcBMBwGCSqGSIb3DQEJBTEPFw0yNjA2MTYyMDI1NDlaMC8GCSqGSIb3DQEJBDEi
# BCAvE7c/5srvo6t+0N8HLvvo46sXYNLoLlcj5ZMeWYdwfjANBgkqhkiG9w0BAQEF
# AASCAgBuBgI03eEjLxYKQWUwpXC1TeT0+0ameMCUqygMExjMeNr4/ZXFQQzPAOPx
# 1JwYloA08F2I+oQxYfywaNoxO6o6Uju7CSfuoDYA1XkD9GnR43u+74wUgm7RL1SU
# lUaqhN3A0r2prGVHC6c2dlyw+DAxGb8bB8h9oGxZ97C4vQa/7zLx589b+q2maGZr
# t4dX8VofJxLQuO8RcxE8Eg0/mv4uuEbj+FihOpRw8lywGjFp9QPl3qYVyHvdrE9C
# pM78b6ddoSmJBceJSyf/Ivr3VJSPx0/ZJuMm9Qz6o7EbopnE9bJ+0ywxJmQdTlbc
# nJnldhH7jTsFRR9a9IaqHdlnCbmZuAD8wRCZpBJNZxKCajPMHgfwu/OO9jjUXjWW
# GyFJ3LkTtsdm12pMdCxcMXDcz+/WUnKxEE/xhHGjfijqneghmET7uoUx+z441+ho
# hEsZTGO6KMDZ/7amuQJgp7NGUHFHzRLW52c8zhuez/UF+7o2pw7DCOC1qe/C+HA7
# zsf/+JoCgq499zrykTRcXImcWXz2QAEo5HRBh0RgW96pQIA4AcK5nhE/80dU9O8V
# 4w1ivM9dmmPlB8JJdDi3U21m8vNzXaHdbPacPafg7cHmceEY98E2zMoUOr0I1m6d
# fFjmw/4DVP8ET+CWCRuycHdySkUo2NDrOVdok5BxpnxRAWyPgQ==
# SIG # End signature block
