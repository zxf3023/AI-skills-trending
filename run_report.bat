@echo off
setlocal EnableExtensions
rem ============================================================
rem  AI Skills Trending - report generator - one-click launcher
rem  Requirements: Python 3.8+  (https://www.python.org/downloads/)
rem  Install tip: tick "Add python.exe to PATH" in the installer.
rem  No extra pip packages needed (standard library only).
rem ============================================================
cd /d "%~dp0" || (echo [ERROR] Cannot enter the script folder. & pause & exit /b 1)

set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe" set "PY=%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe"
)

if not defined PY (
    echo [ERROR] Python was not found on this computer.
    echo Please install Python 3.8 or newer from:
    echo     https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during installation,
    echo then double-click this file again.
    echo.
    pause
    exit /b 1
)

echo Python launcher: %PY%
echo Starting the AI Skills Trending report generator...
echo (If a window does not appear, the program falls back to console mode automatically.)
%PY% "%~dp0github_trending_report.py"
if errorlevel 1 (
    echo.
    echo [ERROR] The program exited with an error. Please read the messages above.
    pause
)
endlocal
