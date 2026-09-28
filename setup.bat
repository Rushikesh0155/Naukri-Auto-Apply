@echo off
rem One-time setup. Creates a private Python environment and downloads the
rem browser Naukri Autopilot drives. Safe to re-run.
setlocal
cd /d "%~dp0"

echo Naukri Autopilot for Windows setup
echo ==================================
echo.

rem The py launcher is what a normal python.org install gives you. Plain
rem python is the fallback for installs that skipped it.
set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  python --version >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo Python 3 is not installed, or it is not on your PATH.
  echo.
  echo Get it from https://www.python.org/downloads/ and run this again.
  echo In the installer, tick "Add python.exe to PATH" on the first screen.
  goto fail
)

for /f "tokens=*" %%v in ('%PY% --version 2^>^&1') do echo Python: %%v

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"
if errorlevel 1 (
  echo.
  echo Python 3.9 or newer is needed.
  echo Get it from https://www.python.org/downloads/ and run this again.
  goto fail
)

rem Windows still caps most paths at 260 characters. The browser packs files
rem a long way down inside this folder, so a folder that already sits deep
rem makes the install fail halfway with a confusing error. Better to say so.
%PY% -c "import os, sys; sys.exit(1 if len(os.getcwd()) > 150 else 0)"
if errorlevel 1 (
  echo.
  echo This folder is too deep inside other folders for Windows to handle.
  echo.
  echo Move the Naukri Autopilot folder somewhere shorter, like your Desktop
  echo or C:\NaukriAutopilot, then run setup.bat again.
  goto fail
)

rem An environment copied from another PC points at a Python that is not here,
rem so check it actually runs and rebuild it if not.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
  if errorlevel 1 (
    echo Rebuilding a broken environment...
    rmdir /s /q ".venv"
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating the environment...
  %PY% -m venv ".venv"
  if errorlevel 1 (
    echo Could not create the environment.
    goto fail
  )
)

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install -q --upgrade pip
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo Could not install the dependencies. Check your internet connection.
  goto fail
)

echo Downloading the browser (about 150 MB, one time)...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 (
  echo Could not download the browser. Check your internet connection.
  goto fail
)

if not exist ".env" copy /y ".env.example" ".env" >nul
if not exist "logs" mkdir "logs"
if not exist "screenshots" mkdir "screenshots"
if not exist "Resume" mkdir "Resume"
if not exist "data" mkdir "data"

rem Which browser will actually run. Informational only, and never fatal: a PC
rem where the downloaded one will not start still works, it just uses Edge
rem instead. Better to say so now than leave it to a log line later.
echo.
".venv\Scripts\python.exe" -c "import common; common.check_browser()"

echo.
echo Done.
echo.
echo Next:
echo   1. Put your resume PDF in the Resume folder
echo   2. Run dashboard.bat
echo   3. Sign in to Naukri from the dashboard, then pick a schedule
echo.
pause
exit /b 0

:fail
echo.
pause
exit /b 1
