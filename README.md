# HenanDiary

纯截图驱动的 Windows 桌面小工具：每隔几分钟截一张全屏图 → 送 AI 分析 → 每晚生成一份日报。数据只存本地，截图绝不落盘。

需求见 `docs/需求文档-日报生成应用-v0.3.md`，技术方案见 `docs/技术方案-v2.0.md`。

## 当前进度

**M0–M8 全部完成**：采集、日报/周报生成、Web 主窗口（今日总览 / 时间线 / 日报周报 / 设置 / 首次引导）、
自动调度与失败补跑、数据管理、打包与安装包均已跑通。

构建产物：`dist/HenanDiary.exe`（PyInstaller 单文件）与
`dist/installer/HenanDiary-0.1.0-setup.exe`（Inno Setup 安装包）。
逐里程碑的交付物与验收记录见 `docs/开发状态.md`。

## 环境准备

依赖用 [uv](https://docs.astral.sh/uv/) 管理：

```bash
uv sync          # 按 pyproject.toml 装依赖
uv lock          # 首次生成 uv.lock 并提交
uv run pytest    # 跑测试
uv run main.py   # 启动（首次弹引导，之后托盘常驻）
```

PyInstaller 是**构建期依赖，未写进 pyproject**（本机无 uv 时改 pyproject 会同步不了 uv.lock），
打包前先手动 `pip install pyinstaller`，再执行 `pyinstaller packaging/app.spec`。

## 目录结构

```
main.py                 入口：初始化 → 单实例 → 主窗口（pywebview）+ 托盘（pystray），并启动调度
config.py               配置读写与数据目录解析（所有模块唯一配置来源）
logger.py               统一日志入口（禁止 print、禁止静默吞异常）
collector/              截图采集：mss 截图 → 压缩 → 送 AI（A）M1
ai/                     AI 客户端 + DPAPI（A）M2
storage/db.py           SQLite 接口【M0 已冻结】
storage/cleanup.py      3 天清理（B）M6
report/                 日报/周报生成（B）M2 / M6
scheduler/              定时任务：采集/日报/覆盖/周报/清理 + 启动补跑（B）M5
ui/api.py               js_api 桥：Web 前端与后端的唯一通道（M8）
ui/single_instance.py   单实例运行（需求 F6）
web/                    Web 主窗口（原生 HTML/CSS/JS，无构建链、无前端框架）
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

截图只以内存字节流送 AI，**不写盘任何位置（含系统 temp）**；送 AI 前统一缩到宽 1024 并转 JPEG
（1920×1080 的截图 base64 后从约 2.9MB 降到约 0.11MB），入库的只有 AI 分析出的文字，保留 3 天。

## 构建与数据安全（M7 前必读）

历史上发生过 PyInstaller 打包清空 `dist/dailylog/`、导致历史记录与报告全丢的事故。构建环节必须满足：

1. 构建输出到独立目录，并显式排除 `data.db`、`reports/`、`logs/`；
2. 执行任何会重建/清理目录的命令前，先确认它的清理行为（查文档或实测）；
3. 破坏性操作前先备份不可再生的数据。

`.gitignore` 里已把上述数据文件排除，请不要为了"方便"把它们加进构建产物。
