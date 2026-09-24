# AGENTS.md

## 项目是什么

纯截图驱动的 Windows 桌面小工具：定时全屏截图 → AI 分析 → 每晚自动生成日报/周报。
数据只存本地（`%APPDATA%\HenanDiary\`），**截图绝不落盘（含系统 temp）**。
M0–M8 已全部完成（采集、日报/周报、Web 主窗口、调度补跑、打包安装）。

## 常用命令

```bash
uv sync                                 # 安装依赖（依赖变更必须 uv lock 并提交 uv.lock）
uv run pytest                           # 跑测试
uv run main.py                          # 启动应用（首次弹引导，之后托盘常驻）
uv run main.py --gen-report 2026-09-25  # 无 GUI 生成指定日期日报后退出
```

- 打包：PyInstaller 是构建期依赖、**未写进 pyproject**——先 `pip install pyinstaller`，再在仓库根目录 `pyinstaller packaging/app.spec`；安装包用 Inno Setup（`packaging/installer.iss`）。
- 未配置 lint / typecheck；代码规范靠人工遵守（见 `docs/开发规范.md`：Python 3.11+、类型注解、行长 ≤100、函数 ≤30 行、文件顶部模块 docstring）。

## 硬规则（违反会出事故）

1. **截图只在内存处理**：mss 截图 → 内存压缩（宽 1024 转 JPEG q80）→ 送 AI，任何情况不写盘。入库的只有 AI 产出的文字（app / category / analysis）。
2. **禁止 print、禁止静默吞异常**（`except: pass`）：一律走 `logger.py`；关键操作必须记日志。
3. **配置唯一来源是 `config.py`**：禁止别的模块自己存配置、写死路径/Key/URL。非法值必须在 `config._validate` 写入前拦死——坏值一旦落盘，scheduler 构建时抛异常且被吞，采集静默停摆而界面仍显示"运行中"。
4. **数据只在 `%APPDATA%\HenanDiary\`**：仓库内出现 `data.db`/`reports/`/`logs/`/`exports/` 都不对（.gitignore 已排除，别塞进构建产物）。
5. **构建安全**：历史上 PyInstaller 打包清空过 dist 里的历史数据。任何会重建/清理目录的命令先确认清理行为再执行，不可再生数据先备份。UPX 保持关闭（杀软误报）。

## 架构边界

- `main.py` 入口：装配单实例、frameless 窗口（pywebview）、托盘（pystray）、调度；`--gen-report` 是无 GUI 通道。
- `collector/screenshot.py` 只管采集一轮：压缩与 AI JSON 解析容错都在这；单轮失败只记 error 不抛（采集循环不能停摆）。
- `ai/client.py` OpenAI 兼容客户端：**必须流式**（Qwen-Omni 要求）；超时 60s、重试 5 次是刻意的——SDK 默认 600s 会拖死采集线程，APScheduler `max_instances=1` 会静默漏采。分类是**封闭集合** `IMAGE_ANALYSIS_CATEGORIES`（日报时间分布按分类本地计数，不能让模型自由发挥）。Key 用 DPAPI 加密存 settings.json。
- `storage/db.py` SQLite 接口 **M0 已冻结**（接口先行规范）：改签名/表结构必须先通知协作者；每操作一连接 + WAL（APScheduler 后台线程调用，禁止跨线程共享连接）。生成失败记 `pending_report`（欠账本），`daily_report` 的行表达已生成的状态，两处不表达同一件事。
- `scheduler/jobs.py` 收敛全部定时任务：采集/日报/覆盖/周报/清理 + 启动补跑。
- `ui/api.py` js_api 桥 = Web 前端与后端**唯一通道**：方法返回可 JSON 序列化的 dict/list，失败不抛异常、统一返回 `{"error": "..."}`；窗口/托盘引用用 `attach()` 注入，所以可脱离 GUI 单测。
- `web/` 原生 HTML/CSS/JS，**无构建链、无前端框架**；窗口拖拽只限 `.pywebview-drag-region`。
- 时间戳一律 ISO8601 字符串，日期一律 `YYYY-MM-DD`；截图间隔只允许 2/5/10 分钟。

## pywebview 坑（改 main.py 前读）

- closing 事件 handler **返回 False 才取消关闭**（语义反直觉，放行真退出才返回 True）。
- WinForms UI 线程回调里同步调 `evaluate_js` 会死锁——必须另起线程（见 `main.on_closing`）。

## Git 约定

- 分支：`main` 只能从 `dev` 合并；功能 `feat/xxx`、修复 `fix/xxx` 从 dev 切（xxx 用英文小写连字符）；小改动直接提交 dev。
- 提交信息 `<type>:<中文描述>`：**冒号后不加空格**，一条消息就是一句中文短句；一个 commit 只做一件事。type ∈ feat/fix/docs/refactor/perf/chore。
- 每完成一个里程碑更新 `docs/开发状态.md`。

## 测试

- pytest；`tests/conftest.py` 的 autouse 夹具把 `APPDATA` 重定向到 tmp_path——测试不碰真实数据目录，日志 handler 每例清理。
- 测试文件命名 `test_<模块名>.py`，放 `tests/` 对应子目录；关键模块（storage / ai / report / scheduler / ui）必须覆盖。

## 文档（改敏感区前先读）

- `docs/开发规范.md` — 代码/Git/接口/测试规范的源头
- `docs/需求文档-日报生成应用-v0.3.md` — 需求（F/D 编号出处）
- `docs/技术方案-v2.0.md` — 技术决策
- `docs/开发状态.md` — 里程碑进度与验收记录
