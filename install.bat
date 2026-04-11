@echo off
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%USERPROFILE%\gphotohandler-venv"

:: ── Python version check ──────────────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo Error: python not found. Install Python 3.10 or later from https://python.org and try again.
    exit /b 1
)

for /f "tokens=2 delims= " %%V in ('python --version 2^>^&1') do set "PY_VER=%%V"
for /f "tokens=1,2 delims=." %%A in ("%PY_VER%") do (
    set "PY_MAJOR=%%A"
    set "PY_MINOR=%%B"
)

if %PY_MAJOR% LSS 3 (
    echo Error: Python 3.10+ is required ^(found %PY_VER%^).
    exit /b 1
)
if %PY_MAJOR% EQU 3 if %PY_MINOR% LSS 10 (
    echo Error: Python 3.10+ is required ^(found %PY_VER%^).
    exit /b 1
)

echo Using Python %PY_VER%

:: ── Virtual environment ───────────────────────────────────────────────────────
if not exist "%VENV_DIR%\" (
    echo Creating virtual environment at %VENV_DIR% ...
    python -m venv "%VENV_DIR%"
) else (
    echo Virtual environment already exists at %VENV_DIR% -- skipping creation.
)

:: ── Dependencies ──────────────────────────────────────────────────────────────
echo Installing Python dependencies ...
"%VENV_DIR%\Scripts\pip" install --quiet --upgrade pip
"%VENV_DIR%\Scripts\pip" install -r "%SCRIPT_DIR%requirements.txt"

:: ── Playwright browser ────────────────────────────────────────────────────────
echo Installing Playwright Chromium ...
"%VENV_DIR%\Scripts\playwright" install chromium

:: ── Done ──────────────────────────────────────────────────────────────────────
echo.
echo Setup complete. Run the app with:
echo   run.bat

endlocal
