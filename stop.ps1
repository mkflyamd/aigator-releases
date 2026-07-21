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
    # Full shutdown: kill all Python processes + tray
    $procs = Get-Process python* -ErrorAction SilentlyContinue
    if ($procs) {
        $procs | ForEach-Object {
            Write-Host "Stopping $($_.ProcessName) (PID $($_.Id))" -ForegroundColor Yellow
            Stop-Process -Id $_.Id -Force
        }
        Write-Host "Dev server stopped." -ForegroundColor Green
    } else {
        Write-Host "No Python processes running." -ForegroundColor Gray
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
