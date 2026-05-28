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
