# 墨迹工坊 InkCraft 功能梳理

本文按模块梳理当前实现的功能、代码位置与接口，便于维护。术语见 [README.md](README.md#术语表)；
设计蓝图（历史文档）见 [framework_architecture.md](framework_architecture.md) 与 [ui_design.md](ui_design.md)。

## 1. 总体链路

```text
手写扫描件 ──(hwbuilder)────────▶ .hwfont 笔迹字库
                                            │
DOCX / PDF / TXT / MD ──(docparse)──▶ DocIR ─┼─(layout: 重排 / 套打)──▶ 单线笔画（纸面坐标 mm）
                                            │
                          (gcode: 路径优化 + 坐标映射) ──▶ GRBL G-code ──(grbl: 流控)──▶ 写字机
```

## 2. 模块清单

| 模块 | 目录 | 主要功能 |
| --- | --- | --- |
| 笔迹字库 SDK | `packages/hwfont_sdk` | `.hwfont`（SQLite + HWS1 笔画编码）读写与校验，同字多异形 |
| 后端入口 | `backend/inkcraft/__main__.py` | `python -m inkcraft`，读取 `.env`，自动选端口并打开浏览器 |
| 配置 | `backend/inkcraft/config.py` | 目录与环境变量（`INKCRAFT_*`，兼容旧 `HANDWRITE_*`） |
| API | `backend/inkcraft/api` | FastAPI REST（`/api/v1`）+ WebSocket 遥测，Contract v1 Pydantic 模型 |
| 持久化 | `backend/inkcraft/core` | SQLite（文档、排版、任务、机台档案）、事件总线、后台任务、版式预设文件库 |
| 文档解析 | `backend/inkcraft/docparse` | DOCX（含 OMML 公式、表格、图表）、PDF（MinerU / PyMuPDF）、TXT/MD（UTF-8/GBK 自动识别）、公式 OCR |
| 排版 | `backend/inkcraft/layout` | 重排、套打、书写区域、分页规则、LaTeX 单线公式、表格与图表手绘、拟人化扰动 |
| 书写者 | `backend/inkcraft/writers` | 笔迹字库热插拔注册表、异形选择器、多字体混写、Hershey 单线兜底 |
| G-code | `backend/inkcraft/gcode` | RDP 简化 + 贪心/2-opt 空移优化、舵机/步进 Z/激光笔控、落笔后与抬笔前暂停、自定义起止代码、外框试跑 |
| 机器适配 | `backend/inkcraft/machine` | 纸面↔机器坐标换算（含旋转）、串口自动识别、固件参数（`$$`）读写与校验；兼容奎享雕刻式控制方案（见 [machine_control.md](machine_control.md)） |
| GRBL 控制 | `backend/inkcraft/grbl` | 128B 字符计数流控、状态解析（含英寸上报换算）、暂停/换笔/续写、急停、MockGrbl 仿真 |
| 前端 | `frontend/src` | React + Zustand + Canvas 2D 工作台：导入、版式、预览、点动、作业控制 |
| 笔迹字库构建 | `colab_builder/hwbuilder` | 采集表生成、扫描切字、笔顺恢复、SDT-LoRA 训练、质检导出 |
| Windows 打包 | `windows/`、`*.bat`、`scripts/package_windows_bundle.py` | 一键安装/启动、MinerU GPU 环境、便携包 |

## 3. 机器相关接口（`/api/v1/machine`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/ports` | 列出串口，标注适配器类型与推荐端口（`recommended`） |
| GET / PUT | `/profiles`、`/profiles/{id}` | 机台档案 |
| POST | `/connect` | `port` 为 `auto` 时自动识别 CH340/CP210x/FTDI 等；连接后读取 `$$` |
| GET / PUT | `/grbl-settings` | 读取固件 `$$`（含版本、英寸上报、告警）/ 写入 `$N=值` |
| POST | `/macros/{index}/run` | 执行档案中的自定义宏 |
| POST | `/jog`、`/zero`、`/pen`、`/move-to`、`/move-to-start`、`/frame`、`/home`、`/raw`、`/unlock`、`/estop` | 点动（纸面方向）、置零、抬落笔、移动、外框试跑、回零、原始指令、解锁、急停 |

版式预设：`GET /layout/presets`（代码内置 + 可选的 `config/presets/*.json` + 用户的 `data/presets/*.json`），
`PUT/DELETE /layout/presets/{id}` 维护用户预设。

## 4. 坐标约定

* **纸面坐标**：毫米，原点在纸张左上角，x 向右、y 向下。排版、预览、外框、换笔位等全部使用纸面坐标。
* **机器坐标**：GRBL 工作坐标（`G92` 置零后的 WPos）。由机台档案（`MachineProfile`）的
  `origin`（零点所在纸角）、`x_axis` / `y_axis`（机器正方向指向纸面哪一侧）、`swap_xy`、
  `invert_x/y`（镜像）、`offset_mm`（整体偏移）、`rotation_deg`（绕纸面中心旋转）共同决定，实现见
  `backend/inkcraft/machine/geometry.py`。点动与工作区边界只使用原点、轴向与对调，不受偏移和旋转影响。
* 前端状态中的 `page_pos` 为后端换算回纸面的笔尖位置；`wpos` 保持机器原始坐标。

## 5. 本次重构要点

1. Python 包 `handwrite` → `inkcraft`，环境变量 `HANDWRITE_*` → `INKCRAFT_*`（旧名仍可用）。
2. `inkcraft.api` 改为惰性导出，消除 `api ↔ gcode ↔ machine` 循环依赖。
3. 新增 `inkcraft.machine` 包，集中处理与具体机器相关的逻辑。
4. 已有数据库启动时自动补充新增的内置机台档案（不会覆盖用户修改）。
5. 版式预设改为服务端文件存储，可通过接口增删。
6. 仓库纳入 git 管理：第三方软件、授权文件、个人手写扫描件与笔迹字库、训练产物与运行数据均不入库。
