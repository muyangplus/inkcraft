# 墨迹工坊 InkCraft — Windows 10/11 安装与使用

Windows 发行包已预编译浏览器工作台（`frontend/dist/`）并内置演示笔迹字库，**无需预先安装 Python 或 Node.js**，解压后双击脚本即可部署。

---

## 一、快速上手

1. **解压到常规本地目录**，路径建议只含英文（如 `D:\inkcraft\`）。
2. **安装环境**：双击根目录 **`安装Windows环境.bat`**
   - 自动安装 `uv` 与独立的 **Python 3.12**；
   - 创建 `.venv` 并安装 FastAPI、PyMuPDF、python-docx、Shapely、PySerial 等依赖（默认使用清华 PyPI 镜像）；
   - 完成后自动自检。
3. **启动工作台**：双击根目录 **`启动墨迹工坊.bat`**
   - 默认端口 `8765`，被占用时自动顺延，并自动打开浏览器。

---

## 二、MinerU GPU 解析（可选）

基础安装已包含 `PyMuPDF`（PDF 解析）与 `python-docx`（DOCX 与 OMML 公式解析），可处理常规 Word 与矢量 PDF。
对扫描版或公式、表格复杂的 PDF，可启用本地 **MinerU `pipeline` GPU** 解析：

1. 安装 NVIDIA 显卡驱动（兼容 CUDA 12.x，建议显存 ≥ 8 GB）。
2. 双击根目录 **`安装MinerU_GPU解析.bat`**
   - 在 `runtime\mineru-venv` 创建独立环境，安装 PyTorch CUDA 12.4 与 `mineru[pipeline]`（不使用高显存占用的 vLLM 后端）；
   - 自动生成 `.env`（`MINERU_BACKEND=pipeline`、`MINERU_VIRTUAL_VRAM_SIZE=8`、10 页分块）。以 12 GB 显存为例，峰值约 8.5 GB；显存不同时请按比例调整 `MINERU_VIRTUAL_VRAM_SIZE`。

---

## 三、连接写字机

1. 插上写字机的 USB 线。若 **设备管理器 → 端口 (COM 和 LPT)** 中出现黄色感叹号，请安装 **CH340** 或 **CP210x** USB 串口驱动。
2. 在工作台「GRBL 连接与档案」中关闭 **Mock 仿真**，串口保持 **自动识别**（COM 号会随 USB 口变化，无需手动选择），选择机台档案后点击 **连接**。
3. 点击 **配置** 设置笔控（舵机 / 步进 Z / 激光）与坐标方向，先用点动面板确认方向并置零，执行 **外框试跑** 确认纸张位置后再开始书写。

详细说明见 [docs/machine_control.md](../docs/machine_control.md)。

---

## 四、常见问题

- **PowerShell 提示无法加载脚本**：直接双击 `.bat` 文件即可，`.bat` 已带 `-ExecutionPolicy Bypass`，无需修改系统策略。
- **无法访问清华镜像**：在 PowerShell 中运行 `.\windows\install_windows.ps1`（不带镜像参数时使用官方源）。
- **如何构建自己的笔迹字库**：在工作台「书写者」中点击 **`+ 构建新笔迹`**，可选择本机构建（GPU / CPU）或 Google Colab 构建（导出任务包）。
