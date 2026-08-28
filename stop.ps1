# AI Gator - Stop Dev Server
# Usage:
#   .\stop.ps1           — stop ALL python processes + tray (full shutdown)
#   .\stop.ps1 -Port 8002 — stop only the instance on port 8002 (leaves primary alive)
#   Note: 8001 is reserved for watchdog — don't use it for dev instances.
param(
    [int]$Port = 0   # 0 = stop everything
)

if ($Port -gt 0) {
    # Targeted stop: find only the Python process(es) listening on $Port
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Host "No process listening on port $Port." -ForegroundColor Gray
        exit 0
    }
    $pids = $conns.OwningProcess | Sort-Object -Unique | Where-Object { $_ -gt 0 }
    foreach ($id in $pids) {
        $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "Stopping $($proc.ProcessName) (PID $id) on port $Port..." -ForegroundColor Yellow
            Stop-Process -Id $id -Force
        }
    }
    Write-Host "Instance on port $Port stopped." -ForegroundColor Green
} else {
    # Full shutdown: kill Gator uvicorn by port ownership (8000/8002/8003/etc)
    # plus any python running the Gator .cmd wrapper in TEMP.
    # Never match by command line alone -- uvicorn runs via a temp .cmd wrapper
    # so its command line does not contain the project path.
    $projectDir = $PSScriptRoot
    $gatorPorts = @(8000, 8002, 8003, 8004, 8005)
    $killed = 0
    foreach ($gPort in $gatorPorts) {
        $portPids = Get-NetTCPConnection -LocalPort $gPort -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess | Sort-Object -Unique | Where-Object { $_ -gt 0 }
        foreach ($id in $portPids) {
            $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
            if ($proc -and $proc.Name -match '^python') {
                Write-Host "Stopping python (PID $id) on port $gPort" -ForegroundColor Yellow
                Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
                $killed++
            }
        }
        # Also catch reloader children via the .cmd wrapper name
        $cmdPattern = "aigator-uvicorn-$gPort"
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^python' -and $_.CommandLine -match $cmdPattern } |
            ForEach-Object {
                Write-Host "Stopping python (PID $($_.ProcessId)) [reloader]" -ForegroundColor Yellow
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                $killed++
            }
    }
    if ($killed -gt 0) {
        Write-Host "Dev server stopped." -ForegroundColor Green
    } else {
        Write-Host "No Gator Python processes running." -ForegroundColor Gray
    }

    # Also clean up any background processes tracked by shell_runner (widget-spawned
    # processes like mouse jigglers, dev servers, etc.)
    $bgPidFile = Join-Path $env:USERPROFILE ".gator\work\bg-pids.json"
    if (Test-Path $bgPidFile) {
        try {
            $bgPids = Get-Content $bgPidFile -Raw | ConvertFrom-Json
            $bgPids.PSObject.Properties | ForEach-Object {
                $pid = [int]$_.Name
                $info = $_.Value
                $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
                if ($proc) {
                    Write-Host "Stopping background task (PID $pid): $($info.command)" -ForegroundColor DarkGray
                    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
                }
            }
            Remove-Item $bgPidFile -Force -ErrorAction SilentlyContinue
        } catch {}
    }

    # Also stop the built-app tray. It relaunches its own backend from AppData on
    # port 8000, which silently shadows the repo dev server (serving stale static).
    $tray = Get-Process AIGator -ErrorAction SilentlyContinue
    if ($tray) {
        $tray | ForEach-Object {
            Write-Host "Stopping AIGator tray (PID $($_.Id))" -ForegroundColor Yellow
            Stop-Process -Id $_.Id -Force
        }
        Write-Host "AIGator tray stopped." -ForegroundColor Green
    }

    # Also stop any orphaned OpenCode servers. `opencode serve` spawns one NODE
    # process per project (not python), listening on ports 8100-8199 (see
    # instance_manager.py _PORT_RANGE). The python kill above never touches them,
    # so across a long dev session they accumulate — each is a ~170MB node
    # process — a real cause of the memory bloat / degraded-WMI hangs. Kill by
    # port range (not by "node" name) so unrelated node tools you run — e.g.
    # chrome-devtools, other MCP servers — are never caught in the sweep.
    $ocConns = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -ge 8100 -and $_.LocalPort -le 8199 }
    $ocPids = $ocConns.OwningProcess | Sort-Object -Unique | Where-Object { $_ -gt 0 }
    if ($ocPids) {
        foreach ($id in $ocPids) {
            $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host "Stopping OpenCode server $($proc.ProcessName) (PID $id)" -ForegroundColor Yellow
                Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
            }
        }
        Write-Host "OpenCode servers stopped." -ForegroundColor Green
    }
}
