# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（M7）。

执行方式（在仓库根目录跑，产物落在仓库内的 build/ 与 dist/，两者都已被 .gitignore 排除）：

    pyinstaller packaging/app.spec

数据安全（动手前先读 README「构建与数据安全」）：
- 真实数据固定放 %APPDATA%\\HenanDiary\\，与安装目录、构建目录完全分离（需求 D12），
  所以打包和运行都不会碰到用户数据；
- 本 spec 不收集 dist/ 下任何已有内容，也不做任何目录清理；
  历史上发生过打包把 dist/dailylog/ 连带历史数据一起清掉的事故，改本文件前先想清楚这一点；
- console=False：桌面工具不弹黑框。若要用 --gen-report 的命令行输出调试，改成 True。
"""

import os

ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))  # noqa: F821 (SPECPATH 由 PyInstaller 注入)

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[],  # 界面图标是代码画的圆点（ui/icons.py），没有资源文件要带
    hiddenimports=[
        "win32crypt",  # pywin32 的 DPAPI 入口，静态分析扫不到
        "apscheduler.schedulers.background",
        "apscheduler.triggers.cron",
        "apscheduler.triggers.interval",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 用不到的标准库与 Qt 模块，压体积（技术方案九：>80MB 时排除未用模块）
        "tkinter",
        "pydoc_data",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtMultimedia",
        "PySide6.QtQml",
        "PySide6.QtQuick",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HenanDiary",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX 压缩会明显提高杀软误报率（技术方案九：杀软误报是高概率风险）
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
