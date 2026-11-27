# 参与贡献

感谢你愿意改进墨迹工坊 InkCraft！提交 Issue 或 Pull Request 前请先阅读本指南。

## 提问与反馈

- **Bug**：在 [Issues](https://github.com/muyangplus/inkcraft/issues) 中描述复现步骤、期望结果与实际结果，
  并附上系统版本、Python/Node 版本、写字机型号与固件（可在连接后访问 `/api/v1/machine/grbl-settings` 获取 `$$` 参数）。
- **功能建议**：说明使用场景与期望效果，尽量附示意图或样例文档。
- **安全问题**：请不要公开提交，按 [SECURITY.md](SECURITY.md) 私下报告。

## 开发环境

```bash
# Python workspace（hwfont_sdk / backend / colab_builder）
uv sync
# 或：python3 -m venv .venv && .venv/bin/pip install -e packages/hwfont_sdk -e backend -e colab_builder

# 前端
cd frontend && npm install && cd ..

# 启动（内置 MockGrbl 仿真，无需真实写字机）
uv run python -m inkcraft
```

前后端联调：

```bash
uv run uvicorn inkcraft.api.app:create_app --factory --reload --port 8765
```

```bash
cd frontend && npm run dev
```

## 提交前检查

```bash
uv run pytest
```

```bash
uv run python scripts/export_openapi.py --check
```

```bash
cd frontend && npm run typecheck && npm run build
```

- 修改了 API 模型或路由时，运行 `uv run python scripts/export_openapi.py` 更新 `docs/openapi.json`，并同步 `frontend/src/api/domain/*.ts` 类型。
- 新功能与 Bug 修复请附带测试；涉及 GRBL 行为的改动请在 `MockGrblTransport` 上覆盖。
- 涉及真实运动的改动（坐标映射、抬落笔、急停、续写）请在描述中写明已在哪台机器上实测。

## 代码约定

- Python ≥ 3.11，类型标注完整；模块分层：`api → core / layout / gcode / grbl / machine → hwfont_sdk`，下层不得导入 `inkcraft.api.app`。
- 排版与预览统一使用 **纸面坐标**（mm，左上原点，y 向下），机器坐标只在 `inkcraft.machine.geometry` 中换算。
- 用户可见文案使用简体中文；代码注释与标识符使用英文。
- 不提交以下内容：第三方商业软件及其授权文件、个人手稿扫描件、训练产物、`data/`、`dist/`、`.env`。

## 提交信息与 Pull Request

- 每个提交聚焦一件事，提交信息用中文简述「做了什么、为什么」，例如 `修复：步进Z轴抬笔方向判断`。
- 建议使用 SSH/GPG 签名提交（`git commit -S`）。
- PR 描述包含：改动概要、测试方式、截图（UI 改动）、关联 Issue。
- 提交即表示你同意以 [Apache License 2.0](LICENSE) 授权你的贡献。
