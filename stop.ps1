# AI Gator - Stop Dev Server
# Kills all Python processes (uvicorn parent + reloader children)
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
