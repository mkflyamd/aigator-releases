@echo off
echo Freeing port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 "') do powershell -Command "Stop-Process -Id %%a -Force -ErrorAction SilentlyContinue" 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001 "') do powershell -Command "Stop-Process -Id %%a -Force -ErrorAction SilentlyContinue" 2>nul

echo Installing dependencies...
pip install -r "%~dp0requirements.txt" -q

echo Starting TeamsPOC...
cd "%~dp0.."
start "" python web/watchdog.py

echo Waiting for server to start...
timeout /t 3 /nobreak >nul

echo Opening browser...
start "" http://localhost:8000
