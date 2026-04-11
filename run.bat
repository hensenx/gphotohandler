@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%USERPROFILE%\gphotohandler-venv"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Error: virtual environment not found at %VENV_DIR%.
    echo Run install.bat first.
    exit /b 1
)

"%VENV_DIR%\Scripts\python" "%SCRIPT_DIR%main.py"

endlocal
