@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Visual2Craft - Qt Quick

echo.
echo   VISUAL2CRAFT  /  Qt Quick Desktop Edition
echo   Original 9f035bee reconstruction core
 echo.

rem Keep dependencies isolated; avoids OS-wide Python/Qt conflicts.
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
set "PIP_USER="

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating isolated Python virtual environment...
    where py >nul 2>&1
    if errorlevel 1 goto missing_python
    set "PY_LAUNCHER="
    call :try_version 3.13
    if not defined PY_LAUNCHER call :try_version 3.12
    if not defined PY_LAUNCHER call :try_version 3.11
    if not defined PY_LAUNCHER call :try_version 3.14
    if not defined PY_LAUNCHER goto missing_python
    !PY_LAUNCHER! -m venv ".venv"
    if errorlevel 1 goto venv_failed
) else (
    echo [1/3] Reusing project-local .venv ...
)

set "PY=%CD%\.venv\Scripts\python.exe"
if not exist "%PY%" goto venv_failed

echo [2/3] Installing PySide6 and preserved reconstruction dependencies...
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto install_failed

echo [3/3] Launching GPU-composited Visual2Craft...
"%PY%" app.py %*
if errorlevel 1 goto launch_failed
exit /b 0

:try_version
py -%1 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY_LAUNCHER=py -%1"
exit /b 0

:missing_python
echo [ERROR] No supported Python found. Install 64-bit Python 3.13 and try again.
pause
exit /b 1
:venv_failed
echo [ERROR] Virtual environment could not be created. Delete only .venv if incomplete.
pause
exit /b 1
:install_failed
echo [ERROR] Dependency install failed inside .venv. Check network and Python version.
echo [TIP] Python 3.13 64-bit is recommended. Copy errors if you need help.
pause
exit /b 1
:launch_failed
echo [ERROR] Visual2Craft could not launch. Please copy the errors above.
pause
exit /b 1
