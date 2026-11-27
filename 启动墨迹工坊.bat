@echo off
chcp 65001 >nul
title InkCraft - GRBL Writing Machine Workbench
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\start_windows.ps1"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Server exited with code %ERRORLEVEL%.
    pause
)
