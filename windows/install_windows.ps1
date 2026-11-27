<#
.SYNOPSIS
  InkCraft - Windows 10/11 One-Click Environment Installer
.DESCRIPTION
  Installs uv (if missing), provisions standalone Python 3.12, creates .venv,
  installs all backend/hwfont_sdk/hwbuilder dependencies, configures workspace .pth,
  generates demo .hwfont files if missing, and verifies installation.
  Frontend dist/ is pre-built so Node.js is NOT required on Windows unless -RebuildFrontend is passed.
#>
param(
    [switch]$UseChinaMirror,
    [switch]$RebuildFrontend
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  墨迹工坊 InkCraft · Windows 环境一键安装程序" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "[路径] $Root"

# 1. Ensure uv is installed
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvCmd) {
    $localUv = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    $cargoUv = Join-Path $env:USERPROFILE ".cargo\bin\uv.exe"
    if (Test-Path $localUv) {
        $env:Path = "$(Split-Path $localUv);$env:Path"
        $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    } elseif (Test-Path $cargoUv) {
        $env:Path = "$(Split-Path $cargoUv);$env:Path"
        $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    }
}

if (-not $uvCmd) {
    Write-Host "`n[1/5] 未检测到 uv，正在自动下载安装 uv..." -ForegroundColor Yellow
    try {
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
        $env:Path = "$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin;$env:Path"
        $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    } catch {
        Write-Host "[警告] uv 官方脚本下载失败，尝试通过 winget 安装..." -ForegroundColor Yellow
        winget install --id=astral-sh.uv -e --accept-package-agreements --accept-source-agreements
        $env:Path = "$env:USERPROFILE\.local\bin;$env:LOCALAPPDATA\Microsoft\WinGet\Links;$env:Path"
        $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    }
}

if (-not $uvCmd) {
    throw "无法自动安装 uv，请手动安装 Python 3.12 或访问 https://docs.astral.sh/uv/ 后重试。"
}
Write-Host "[1/5] uv 已就绪: $($uvCmd.Source)" -ForegroundColor Green

# 2. Provision standalone Python 3.12 & create .venv
Write-Host "`n[2/5] 正在配置 Python 3.12 独立虚拟环境 (.venv)..." -ForegroundColor Cyan
$venvDir = Join-Path $Root ".venv"
$venvPy = Join-Path $venvDir "Scripts\python.exe"

# Remove incompatible Linux .venv if copied over
if ((Test-Path $venvDir) -and (-not (Test-Path $venvPy))) {
    Write-Host "[提示] 检测到非 Windows 虚拟环境目录，正在重建 Windows .venv..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $venvDir
}

uv python install 3.12
uv venv $venvDir --python 3.12

# 3. Install Python dependencies
Write-Host "`n[3/5] 正在安装后端、文档解析、单线排版与 GRBL 串口依赖..." -ForegroundColor Cyan
$reqFile = Join-Path $Root "windows\requirements-windows.txt"
$pipArgs = @("pip", "install", "--python", $venvPy, "-r", $reqFile)
if ($UseChinaMirror) {
    Write-Host "[镜像] 使用清华 PyPI 镜像源加速下载..." -ForegroundColor DarkCyan
    $pipArgs += @("--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple")
}
& uv @pipArgs

# 4. Write workspace .pth so `python -m inkcraft` & `python -m hwbuilder` work everywhere
Write-Host "`n[4/5] 正在注册本地工作区包 (hwfont_sdk / backend / colab_builder)..." -ForegroundColor Cyan
$sitePackages = Join-Path $venvDir "Lib\site-packages"
$pthFile = Join-Path $sitePackages "inkcraft_workspace.pth"
$pthContent = @(
    (Join-Path $Root "packages\hwfont_sdk"),
    (Join-Path $Root "backend"),
    (Join-Path $Root "colab_builder")
) -join "`r`n"
Set-Content -Path $pthFile -Value $pthContent -Encoding UTF8

# Generate demo .hwfont files if fonts/ is empty
$fontsDir = Join-Path $Root "fonts"
$existingFonts = @(Get-ChildItem -Path $fontsDir -Filter "*.hwfont" -ErrorAction SilentlyContinue)
if ($existingFonts.Count -eq 0) {
    Write-Host "[字库] 正在生成内置示例 .hwfont 字库..." -ForegroundColor Cyan
    & $venvPy (Join-Path $Root "scripts\generate_demo_writers.py")
}

# Optional frontend rebuild (already pre-built in frontend/dist)
$distIndex = Join-Path $Root "frontend\dist\index.html"
if ($RebuildFrontend -or (-not (Test-Path $distIndex))) {
    $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
    if ($npmCmd) {
        Write-Host "[前端] 正在构建前端工作台 (frontend/dist)..." -ForegroundColor Cyan
        & npm --prefix (Join-Path $Root "frontend") install
        & npm --prefix (Join-Path $Root "frontend") run build
    } elseif (-not (Test-Path $distIndex)) {
        Write-Host "[警告] 未找到预编译 frontend/dist 且本机未安装 Node.js，请安装 Node.js 20+ 后重试。" -ForegroundColor Yellow
    }
} else {
    Write-Host "[前端] 已检测到预编译前端产物 frontend\dist（无需安装 Node.js）" -ForegroundColor Green
}

# 5. Self-check
Write-Host "`n[5/5] 正在执行 Windows 环境自检..." -ForegroundColor Cyan
& $venvPy -c @"
import sys, serial, fitz, docx, shapely, fastapi, uvicorn
import hwfont_sdk, inkcraft, hwbuilder
from hwbuilder.local_runner import probe_capabilities
caps = probe_capabilities()
print('[OK] Python:', sys.version.split()[0])
print('[OK] Core modules loaded: hwfont_sdk, inkcraft, hwbuilder, pyserial, pymupdf, shapely')
print('[OK] GPU Probe:', caps.get('gpu_name') or 'CPU mode', 'VRAM(MB):', caps.get('vram_mb'))
"@

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host "  安装完成！双击根目录「启动墨迹工坊.bat」即可打开工作台。" -ForegroundColor Green
Write-Host "  如需在 NVIDIA GPU 上启用本地 MinerU GPU 解析 PDF，" -ForegroundColor Green
Write-Host "  可再双击「安装MinerU_GPU解析.bat」。" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
