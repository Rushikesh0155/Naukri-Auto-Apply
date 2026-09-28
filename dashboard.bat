@echo off
rem Start the control panel and open it in the browser.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Not set up yet. Run setup.bat first.
  echo.
  pause
  exit /b 1
)

rem server.py works the port out the same way it does when it starts: the
rem environment first, then .env, then 8777. Asking it keeps the two from ever
rem disagreeing, and means this file never has to parse .env itself.
set "PORT="
for /f "usebackq delims=" %%p in (`".venv\Scripts\python.exe" server.py --print-port`) do set "PORT=%%p"
if not defined PORT set "PORT=8777"

".venv\Scripts\python.exe" server.py --probe
if errorlevel 1 (
  rem pythonw, so the dashboard sits in the background with no console window
  rem left open behind it.
  start "" ".venv\Scripts\pythonw.exe" server.py
  timeout /t 2 /nobreak >nul 2>&1
) else (
  echo Already running on port %PORT%.
)

start "" "http://127.0.0.1:%PORT%"
exit /b 0
