@echo off
chcp 65001 >nul
title Handwrite Studio - MinerU RTX 4070 Super GPU Setup
echo Starting MinerU Pipeline GPU Installer (12GB VRAM Safe Mode)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\install_mineru_gpu_windows.ps1" -UseChinaMirror
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] MinerU GPU setup failed with exit code %ERRORLEVEL%.
    pause
    exit /b %ERRORLEVEL%
)
echo.
pause
