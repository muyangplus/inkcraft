# 墨迹工坊 (Handwrite Studio) — Windows 10/11 安装与使用指南

本发行包已**预编译前端工作台**（`frontend/dist/`）并内置示例 `.hwfont` 笔迹库，**Windows 本机无需预先安装 Python 或 Node.js**，解压后双击脚本即可完成部署。

---

## 一、快速上手（两步完成）

1. **解压到纯英文或常规本地目录**（如 `D:\handwrite\`）。
2. **首次安装环境**：双击根目录 **`安装Windows环境.bat`**
   - 自动安装 `uv` 与独立 **Python 3.12**；
   - 创建 Windows 专属 `.venv` 并安装 FastAPI、PyMuPDF、python-docx、Shapely、PySerial 等全部依赖（默认已启用清华 PyPI 镜像加速）；
   - 自动完成环境自检。
3. **启动工作台**：双击根目录 **`启动墨迹工坊.bat`**
   - 自动避开已占用端口（默认 `8765`，占用时自动顺延），并**自动弹出浏览器**打开工作台界面。

---

## 二、RTX 4070 Super (12GB) 本地 MinerU GPU 解析（可选增强）

基础安装已内置 `PyMuPDF`（PDF 解析）与 `python-docx`（DOCX + OMML 数学公式解析），可直接处理常规 Word 与矢量 PDF。  
如需对**复杂学术扫描 PDF / 复杂公式与表格**启用本地 **MinerU Pipeline GPU** 加速：

1. 确保已安装 NVIDIA 显卡驱动（CUDA 12.x 兼容）。
2. 双击根目录 **`安装MinerU_4070Super_Windows.bat`**
   - 会在 `runtime\mineru-venv` 下创建独立 GPU 隔离环境，安装 PyTorch CUDA 12.4 + `mineru[pipeline]`（严格禁用高显存 vLLM 后端）；
   - 自动生成 `.env` 配置（`MINERU_BACKEND=pipeline`、`MINERU_VIRTUAL_VRAM_SIZE=8`、10 页分块），将 4070 Super 显存峰值稳控在 8.5GB 以内。

---

## 三、连接真实 GRBL 写字机械臂（Windows USB 串口）

1. 插入机械臂 USB 线后，在 **Windows 设备管理器 → 端口 (COM 和 LPT)** 查看串口号（常见为 `COM3`、`COM4` 等）。
   - 若显示黄色感叹号，请安装常见的 **CH340** 或 **CP2102** USB 转串口驱动。
2. 打开工作台后，确认顶部处于 **`实际使用`** 模式、右侧 **`Mock GRBL 仿真模式`** 关闭，点击串口刷新按钮选择对应 `COMx`（波特率默认 `115200`），点击 **`连接`**。
3. 点击 **`配置`** 选择您的抬落笔类型：**舵机 (`M5` 抬 / `M3 S90` 落)** 或 **步进 Z 轴 (`G0/G1 Z`)**，先使用点动盘对零并执行 **`外框试跑`** 确认纸张位置后再开始书写。

---

## 四、常见问题

- **Q: PowerShell 提示无法加载脚本？**  
  请直接双击 `.bat` 文件启动，`.bat` 已自带 `-ExecutionPolicy Bypass`，无需修改系统策略。
- **Q: 网络无法访问清华镜像？**  
  可在 PowerShell 中运行不带镜像参数的官方源安装：`.\windows\install_windows.ps1`。
- **Q: 如何在本地或云端构建自己的 `.hwfont` 笔迹？**  
  在工作台左侧 **`笔迹库`** 点击 **`+ 构建新笔迹`**，即可自由选择 **本机离线构建（GPU/CPU）** 或 **云端 Google Colab 构建（一键导出任务包）**。
