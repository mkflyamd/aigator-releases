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
    # can't fill the buffer and deadlock while we animate the spinner. CAPTURED
    # (not discarded) - real gap found via user report: a pip failure ("Dependency
    # install failed") gave zero clue why, only a generic "corporate network?"
    # guess, when the actual cause (e.g. a transitive dep needing a Rust source
    # build) was sitting right there in the output the whole time.
    $captured = [System.Collections.Generic.List[string]]::new()
    $sink = { if ($null -ne $EventArgs.Data) { $Event.MessageData.Add($EventArgs.Data) } }
    $oe = Register-ObjectEvent -InputObject $p -EventName OutputDataReceived -Action $sink -MessageData $captured
    $ee = Register-ObjectEvent -InputObject $p -EventName ErrorDataReceived -Action $sink -MessageData $captured
    [void]$p.Start()
    $p.BeginOutputReadLine()
    $p.BeginErrorReadLine()
    $spin = @('|', '/', '-', [char]92)
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
    if ($code -ne 0 -and $captured.Count -gt 0) {
        $safeName = ($Label -replace '[^a-zA-Z0-9]+', '-').Trim('-')
        $logPath = Join-Path $env:TEMP "aigator-wakegator-$safeName.log"
        $captured | Out-File -FilePath $logPath -Encoding utf8
        Write-Warn "$Label failed (exit $code). Last output:"
        $captured | Select-Object -Last 15 | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }
        Write-Info "Full output: $logPath"
    }
    return ($code -eq 0)
}

# Re-brand a portable electron.exe so the Windows taskbar button shows the AI
# Gator icon instead of the default Electron atom. rcedit (a tiny single-file
# tool from the electron org) is used for version strings, but its --set-icon
# silently fails on some Electron builds (reports exit 0 but never writes the
# icon resource). We use a Python helper (tray/brand_icon.py) that calls the
# Windows UpdateResourceW API directly — this reliably embeds the icon.
# Entirely best-effort: any failure just leaves the atom icon, app still runs.
function Set-ElectronBranding {
    param([string]$ExePath)
    $icon = Join-Path $projectDir "build\aigator_icon.ico"
    if (-not (Test-Path $icon)) { return }
    # First try rcedit for version strings (ProductName etc.)
    try {
        $rcedit = Join-Path $env:TEMP "aigator-rcedit-x64.exe"
        if (-not (Test-Path $rcedit)) {
            $rceditUrl = "https://github.com/electron/rcedit/releases/download/v2.0.0/rcedit-x64.exe"
            Invoke-WebRequest -Uri $rceditUrl -OutFile $rcedit -UseBasicParsing -ErrorAction Stop
        }
        & $rcedit $ExePath --set-version-string "ProductName" "AI Gator" --set-version-string "FileDescription" "AI Gator" 2>&1 | Out-Null
    } catch { }
    # Embed the icon via Python (UpdateResourceW API) — rcedit --set-icon is unreliable
    $brandScript = Join-Path $projectDir "tray\brand_icon.py"
    if (Test-Path $brandScript) {
        # Use venv Python if available, else the system Python found in Step 1
        $brandPy = $venvPy
        if (-not $brandPy -or -not (Test-Path $brandPy)) { $brandPy = $pyCmd }
        if ($brandPy) {
            try {
                & $brandPy $brandScript $ExePath $icon "AI Gator" 2>&1 | ForEach-Object { Write-Info $_ }
                if ($LASTEXITCODE -eq 0) { Write-Info "Branded the app icon (taskbar shows the gator)." }
                else { Write-Info "Icon branding returned non-zero — taskbar may show the default icon." }
            } catch {
                Write-Info "Could not brand the Electron icon: $($_.Exception.Message)"
            }
        }
    } else {
        # Fallback: try rcedit --set-icon (may silently fail)
        try { & $rcedit $ExePath --set-icon $icon 2>&1 | Out-Null } catch { }
        Write-Info "Branded via rcedit (may not embed icon — use tray/brand_icon.py for reliable branding)."
    }
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
        # Download with live progress (spinner + elapsed, ~40 MB)
        $spin = @('|', '/', '-', [char]92)
        $i = 0
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $job = Start-Job -ScriptBlock {
            param($url, $out)
            Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
        } -ArgumentList $nodeUrl, $tmpZip
        while ($job.State -eq 'Running') {
            $i++
            $line = "      {0} Downloading Node.js {1}  [{2}s]" -f $spin[$i % 4], $nodeVersion, [int]$sw.Elapsed.TotalSeconds
            Write-Host ("`r" + $line.PadRight(78)) -ForegroundColor DarkGray -NoNewline
            Start-Sleep -Milliseconds 150
        }
        Receive-Job $job -ErrorAction Stop | Out-Null
        Remove-Job $job
        Write-Host ("`r" + (" " * 78) + "`r") -NoNewline
        Write-Info "Extracting Node.js..."
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

# -- Bundle OpenCode (pinned version, into the portable Node above) -----------
# Same reasoning as the Node.js bundle above: install into our own portable
# Node's global prefix (--prefix $nodeDir) rather than the user's system
# npm, so it's fully self-contained in the app folder and never touches or
# depends on anything the user has installed. Pinned to an exact version,
# not "latest" - see docs/internal/OpenCodeIntegrationPlan.md section 4. Non-fatal:
# if this fails, the app still starts; only the OpenCode coding-agent panel
# won't be available.
$opencodeVersion = "1.18.14"
$opencodeCmd = Join-Path $nodeDir "opencode.cmd"

# Materialize node_modules/opencode-ai/bin/opencode.exe (the file the shim runs)
# from the surviving platform package when npm's postinstall failed to. That
# postinstall is destructive-on-retry (it unlinks the binary before re-copying
# and only succeeds if a verify step passes), so a re-run could leave the binary
# deleted-and-not-replaced - the recurring "OpenCode won't start" outage.
# AVX2-aware: NEVER place the AVX2 build on a CPU without AVX2 (illegal-
# instruction crash). Mirrors the runtime self-heal in instance_manager.py.
function Repair-OpencodeBinary {
    $ocAi   = Join-Path $nodeDir "node_modules\opencode-ai"
    $target = Join-Path $ocAi "bin\opencode.exe"
    if (Test-Path $target) { return $true }
    $avx2 = $false
    try {
        $sig = '[DllImport("kernel32.dll")] public static extern bool IsProcessorFeaturePresent(int f);'
        $k = Add-Type -MemberDefinition $sig -Name Kernel32Avx -Namespace Win32 -PassThru
        $avx2 = $k::IsProcessorFeaturePresent(40)   # PF_AVX2_INSTRUCTIONS_AVAILABLE
    } catch { $avx2 = $false }
    $pkgs = if ($avx2) { @("opencode-windows-x64", "opencode-windows-x64-baseline") }
            else       { @("opencode-windows-x64-baseline") }   # baseline only on non-AVX2
    foreach ($pkg in $pkgs) {
        $src = Join-Path $ocAi "node_modules\$pkg\bin\opencode.exe"
        if (Test-Path $src) {
            New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
            Copy-Item $src $target -Force
            Write-Info "Repaired OpenCode binary from $pkg."
            return (Test-Path $target)
        }
    }
    return $false
}

# Verify opencode actually RUNS - not just that the .cmd shim file exists (npm
# always writes the shim even when the real binary is missing, which is exactly
# how a broken install used to report "ready").
function Test-OpencodeRuns {
    if (-not (Test-Path $opencodeCmd)) { return $false }
    $v = & $opencodeCmd --version 2>$null
    # --version can emit >1 line; take the last non-empty line so an array
    # doesn't make `-eq` a loose (any-match) comparison that weakens the gate.
    $v = ($v | Where-Object { $_ } | Select-Object -Last 1)
    return ($LASTEXITCODE -eq 0 -and "$v".Trim() -eq $opencodeVersion)
}

if (Test-OpencodeRuns) {
    Write-OK "OpenCode $opencodeVersion already present."
} elseif ((Repair-OpencodeBinary) -and (Test-OpencodeRuns)) {
    # Cheap, non-destructive in-place repair FIRST - avoids re-triggering the
    # fragile postinstall when the platform package is still present.
    Write-OK "OpenCode $opencodeVersion ready (repaired in place)."
} elseif ((Test-Path $nodeExe) -or (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Info "Installing OpenCode $opencodeVersion (coding agent)..."
    $ocLog = Join-Path $env:TEMP "aigator-opencode-install.log"
    try {
        # Live spinner while npm downloads opencode-ai + its ~173MB platform
        # binary, so the user knows something's happening (matches the Node.js
        # download spinner). Output is captured to $ocLog for diagnosis.
        $npmCmd = Join-Path $nodeDir "npm.cmd"
        $ocJob = Start-Job -ScriptBlock {
            param($npm, $ver, $prefix, $log)
            & $npm install -g "opencode-ai@$ver" --prefix $prefix *> $log
            $LASTEXITCODE
        } -ArgumentList $npmCmd, $opencodeVersion, $nodeDir, $ocLog
        $spin = @('|', '/', '-', [char]92); $si = 0
        $osw = [System.Diagnostics.Stopwatch]::StartNew()
        while ($ocJob.State -eq 'Running') {
            $si++
            $line = "      {0} Installing OpenCode {1}  [{2}s]" -f $spin[$si % 4], $opencodeVersion, [int]$osw.Elapsed.TotalSeconds
            Write-Host ("`r" + $line.PadRight(78)) -ForegroundColor DarkGray -NoNewline
            Start-Sleep -Milliseconds 150
        }
        $npmExit = Receive-Job $ocJob
        Remove-Job $ocJob
        Write-Host ("`r" + (" " * 78) + "`r") -NoNewline
        if (-not (Test-OpencodeRuns)) { Repair-OpencodeBinary | Out-Null }  # postinstall may have failed the copy
        if (Test-OpencodeRuns) {
            Write-OK "OpenCode $opencodeVersion ready."
        } else {
            # Loud but NON-fatal: the rest of AI Gator still runs; only the
            # coding-agent panel is unavailable until this is resolved.
            Write-Warn "OpenCode setup didn't complete (npm exit $npmExit) - the coding-agent panel may not work."
            Write-Info "Install log: $ocLog"
        }
    } catch {
        Write-Warn "Could not set up OpenCode: $($_.Exception.Message)"
        Write-Info "The coding-agent panel may not work until this is resolved."
    }
} else {
    Write-Warn "Skipping OpenCode setup - Node.js bundle is not present."
}

# -- Bundle Electron (portable, hosts the native Slack/Teams/Outlook panes) -----
# AI Gator's UI now runs inside an Electron shell (shell/main.js) - a plain
# browser tab cannot tile the native Slack/Teams/Outlook panes or inject their
# pin buttons (WebContentsView must be a genuine top-level document). So Electron
# is REQUIRED, not optional. We bundle a portable Electron into the app folder
# the same way as Node above: download the pinned platform zip to TEMP, extract,
# copy in, and delete the scratch. The extracted binary (electron\electron.exe)
# is the "already present?" marker so re-runs skip the ~150 MB download.
$electronVersion = "43.0.0"
$electronDir = Join-Path $projectDir "electron"
# We do NOT rename electron.exe -> "AI Gator.exe". Renaming created a duplicate
# Start Menu entry (Windows auto-indexes the exe, producing an "AI Gator.exe"
# entry alongside the "AI Gator" .lnk shortcut), which caused AppUserModelID
# resolution confusion — Windows could match the running process to the wrong
# entry and show the default Electron atom in the taskbar. shell/main.js's
# app.setName('AI Gator') fixes the Installed-apps label; the embedded icon
# (Set-ElectronBranding below) fixes the taskbar button. The process name in
# Task Manager reads "electron" instead of "AI Gator", which is acceptable.
$electronExe = Join-Path $electronDir "electron.exe"
if (Test-Path $electronExe) {
    Write-OK "Electron runtime already present."
} else {
    Write-Info "Setting up Electron runtime (hosts the native app panes)..."
    try {
        $electronZipName = "electron-v$electronVersion-win32-x64"
        $electronUrl = "https://github.com/electron/electron/releases/download/v$electronVersion/$electronZipName.zip"
        $tmpZip = Join-Path $env:TEMP "$electronZipName.zip"
        $tmpEx  = Join-Path $env:TEMP "aigator_electron_tmp"
        if (Test-Path $tmpEx) { Remove-Item $tmpEx -Recurse -Force -ErrorAction SilentlyContinue }
        # Download with live progress (spinner + elapsed, ~150 MB)
        $spin = @('|', '/', '-', [char]92)
        $i = 0
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $job = Start-Job -ScriptBlock {
            param($url, $out)
            Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
        } -ArgumentList $electronUrl, $tmpZip
        while ($job.State -eq 'Running') {
            $i++
            $line = "      {0} Downloading Electron {1}  [{2}s]" -f $spin[$i % 4], $electronVersion, [int]$sw.Elapsed.TotalSeconds
            Write-Host ("`r" + $line.PadRight(78)) -ForegroundColor DarkGray -NoNewline
            Start-Sleep -Milliseconds 150
        }
        Receive-Job $job -ErrorAction Stop | Out-Null
        Remove-Job $job
        Write-Host ("`r" + (" " * 78) + "`r") -NoNewline
        Write-Info "Extracting Electron..."
        # The Electron zip has electron.exe at the archive ROOT (no versioned
        # top-level folder to flatten, unlike Node), so extract straight in.
        New-Item -ItemType Directory -Force -Path $electronDir | Out-Null
        Expand-Archive -Path $tmpZip -DestinationPath $electronDir -Force
        Remove-Item $tmpZip -Force -ErrorAction SilentlyContinue
        Remove-Item $tmpEx -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path $electronExe) {
            Write-OK "Electron $electronVersion ready."
            # Embed the gator icon into electron.exe via the UpdateResourceW API
            # (tray/brand_icon.py). When the raw exe runs, Windows shows THAT
            # exe's embedded icon (the blue Electron atom) for the taskbar button
            # - shell/main.js's BrowserWindow icon fixes the loading page but
            # Windows swaps to the exe's own icon once the taskbar button resolves,
            # which is the "gator flips to atom" bug. rcedit --set-icon silently
            # fails on some Electron builds (exit 0, no resource written), so we
            # use the Python helper that calls UpdateResourceW directly. Non-fatal:
            # the app runs either way; only the taskbar icon falls back to the atom.
            Set-ElectronBranding $electronExe
        }
        else { Write-Warn "Electron setup didn't complete - the app window may not open." }
    } catch {
        Write-Warn "Could not set up Electron: $($_.Exception.Message)"
        Write-Info "The native app panes need Electron - try re-running WakeGator."
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
    if (-not (Invoke-WithProgress $pyCmd "Creating virtual environment" @("-m", "venv", $venvDir))) {
        Write-Err "Failed to create virtual environment."; Read-Host "      Press Enter to exit"; exit 1
    }
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
# Stamp a .lnk with an explicit AppUserModelID so Windows can map the running
# app (which calls app.setAppUserModelId('com.amd.aigator') in shell/main.js)
# back to THIS shortcut - that's how toast notifications and taskbar grouping
# resolve the AI Gator icon instead of the default Electron/Python icon.
# WScript.Shell can't set the AppID, so we call the tray helper (Python +
# pywin32, already a hard dependency) which uses the shell property store.
# Best-effort: if it fails the app still runs, only the toast/taskbar icon may
# fall back to a default.
$AIGATOR_APPID = "com.amd.aigator"
function Set-ShortcutAppId {
    param([string]$LnkPath, [string]$AppId)
    $helper = Join-Path $projectDir "tray\set_shortcut_appid.py"
    if (-not (Test-Path $helper)) { return }
    try { & $venvPy $helper $LnkPath $AppId 2>&1 | Out-Null } catch {
        Write-Info "Could not stamp AppUserModelID on shortcut (notifications may show a default icon)."
    }
}
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
    Set-ShortcutAppId $Path $AIGATOR_APPID
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

# Clear stale .pyc cache — git operations (checkout, rebase, pull) can change
# .py file contents without updating their mtime, so Python trusts stale .pyc
# files and loads old bytecode. This caused the recurring silent-stream bug
# where get_fallback_provider existed in the .py but not in the cached .pyc.
# ~1s cost; guarantees fresh compilation from source every launch.
Get-ChildItem -Path $projectDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\.venv|node_modules|build' } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Start-Process $venvPyw -ArgumentList "`"$trayScript`"" -WorkingDirectory $projectDir -WindowStyle Hidden
Write-OK "AI Gator is starting in your system tray."

# The tray opens the animated loading page in the browser as soon as the
# watchdog is alive (~1s) - that's the user's visual progress indicator.
# Here in the terminal we poll /health (the FULL app, after prefetch) with a
# spinner, so the window stays a live progress bar and only declares success
# once the app is actually usable.
$spin = @('|', '/', '-', [char]92)
$si = 0
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$ready = $false
# The tray first KILLS any stale server on :8000 (identity sweep + port kill,
# ~1s) and then starts a fresh one. If we polled :8000 immediately, the dying
# old server would answer 200 on our first check and we'd exit instantly with
# no spinner - while the real new server is still starting. So:
#   1) give eviction a head start before the first poll
#   2) require TWO consecutive successes so a stale server's last gasp doesn't
#      count as ready
Start-Sleep -Seconds 2
while ($sw.Elapsed.TotalSeconds -lt 90) {
    $line = "      {0} Loading AI Gator...  [{1}s]" -f $spin[$si % 4], [int]$sw.Elapsed.TotalSeconds
    Write-Host ("`r" + $line.PadRight(78)) -ForegroundColor DarkGray -NoNewline
    $si++
    # /ready (on the watchdog, :8001) only returns ready:true once the FULL app
    # at :8000 answers /health AND has finished starting. We poll that single
    # source of truth instead of :8000/health directly, which goes 200 as soon
    # as uvicorn binds - long before prefetch/frontend are actually usable.
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8001/ready" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        $j = $r.Content | ConvertFrom-Json
        if ($j.ready) { $ready = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 300
}
Write-Host ("`r" + (" " * 78) + "`r") -NoNewline

# -- Done ----------------------------------------------------------------------
Write-Host ""
Write-Gator "  ============================================================" "DarkGray"
Write-Host ""
if ($ready) {
    Write-Gator "   The gator is awake!  Chomp chomp." "Green"
    Write-Host ""
    Write-Info  "AI Gator is opening in its app window."
} else {
    Write-Warn  "AI Gator is taking longer than usual to start."
    Write-Info  "It should still open shortly - check for the app window and system tray."
}
Write-Info  "Look for the gator icon in your system tray (bottom-right)."
Write-Host ""
Write-Gator "   To open it again later:" "White"
Write-Info  "Start Menu  ->  search 'AI Gator'   (or the desktop icon)"
Write-Host ""
Read-Host "      Press Enter to close this window"
