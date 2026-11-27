@echo off
chcp 65001 >nul
title InkCraft - Windows Environment Setup
echo Starting InkCraft Windows Installer...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\install_windows.ps1" -UseChinaMirror
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Installation failed with exit code %ERRORLEVEL%.
    pause
    exit /b %ERRORLEVEL%
)
echo.
pause
