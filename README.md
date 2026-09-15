# HenanDiary

纯截图驱动的 Windows 桌面小工具：每隔几分钟截一张全屏图 → 送 AI 分析 → 每晚生成一份日报。数据只存本地，截图绝不落盘。

需求见 `docs/需求文档-日报生成应用-v0.3.md`，技术方案见 `docs/技术方案-v2.0.md`。

## 当前进度

**M0 完成**：项目骨架与接口冻结。截图采集（M1）、日报生成（M2）等尚未实现，明细见 `docs/开发状态.md`。

## 环境准备

依赖用 [uv](https://docs.astral.sh/uv/) 管理：

```bash
uv sync          # 按 pyproject.toml 装依赖
uv lock          # 首次生成 uv.lock 并提交
uv run pytest    # 跑测试
uv run main.py   # 启动骨架（只初始化日志与配置目录）
```

## 目录结构

```
main.py                 入口：初始化 → 配置 → 后续接托盘
config.py               配置读写与数据目录解析（所有模块唯一配置来源）
logger.py               统一日志入口（禁止 print、禁止静默吞异常）
collector/              截图采集（A）M1
ai/                     AI 客户端 + DPAPI（A）M2
storage/db.py           SQLite 接口【M0 已冻结】
storage/cleanup.py      3 天清理（B）M6
report/                 日报/周报生成（B）M2 / M6
scheduler/              定时任务（B）M5
ui/                     托盘、查看窗口、设置、引导（B）M3 / M4
packaging/              打包与安装包（共同）M7
tests/                  pytest
```

## 数据位置

固定 `%APPDATA%\HenanDiary\`，与安装路径完全分离：

```
data.db                  SQLite 主库
config/settings.json     用户配置（API Key 为 DPAPI 加密后的密文）
reports/daily|weekly/    日报与周报 Markdown，永久保留
logs/app.log             轮转日志（1MB × 5）
exports/                 用户手动导出
```

截图只以内存字节流送 AI，**不写盘任何位置（含系统 temp）**；入库的只有 AI 分析出的文字，保留 3 天。

## 构建与数据安全（M7 前必读）

历史上发生过 PyInstaller 打包清空 `dist/dailylog/`、导致历史记录与报告全丢的事故。构建环节必须满足：

1. 构建输出到独立目录，并显式排除 `data.db`、`reports/`、`logs/`；
2. 执行任何会重建/清理目录的命令前，先确认它的清理行为（查文档或实测）；
3. 破坏性操作前先备份不可再生的数据。

`.gitignore` 里已把上述数据文件排除，请不要为了"方便"把它们加进构建产物。
