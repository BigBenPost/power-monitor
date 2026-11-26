@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
    echo Install uv first. See README.md for the installation command.
    pause
    exit /b 1
)
uv run --locked powerlog %*
if errorlevel 1 pause
