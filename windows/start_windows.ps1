<#
.SYNOPSIS
  InkCraft - Windows One-Click Launcher
#>
param(
    [int]$Port = 8765,
    [string]$BindHost = "127.0.0.1",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "[提示] 尚未检测到 Windows 虚拟环境，正在先执行一键安装..." -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot "install_windows.ps1") -UseChinaMirror
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  正在启动 墨迹工坊 InkCraft..." -ForegroundColor Cyan
Write-Host "  关闭本窗口即可停止服务" -ForegroundColor DarkGray
Write-Host "============================================================" -ForegroundColor Cyan

$runArgs = @("-m", "inkcraft", "--host", $BindHost, "--port", "$Port", "--auto-port")
if (-not $NoBrowser) {
    $runArgs += "--open-browser"
}
& $venvPy @runArgs
