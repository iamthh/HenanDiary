; HenanDiary 安装包脚本（Inno Setup 6，M7）
;
; 编译：iscc packaging\installer.iss
; 前置：先跑 pyinstaller packaging\app.spec，产出 dist\HenanDiary.exe
; 产物：dist\installer\HenanDiary-0.1.0-setup.exe
;
; 两条硬约束：
; 1. 按用户要求，不做开机自启——本文件不写 [Registry] 的 Run 项，保持干净；
; 2. 绝不碰 %APPDATA%\HenanDiary\——卸载只删安装目录里的程序文件，
;    用户数据（data.db、日报、周报、日志）按需求 D12 与安装目录分离，一律保留。

#define AppName "HenanDiary"
#define AppVersion "0.1.0"
#define AppExeName "HenanDiary.exe"

[Setup]
; AppId 唯一标识本应用，升级与卸载靠它认人；首次发布后不要再改
AppId={{7C1E5B42-9A3D-4E77-8F51-2D6B0C9E4A18}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=HenanDiary
; 需求 F6：默认装到 C:\Program Files\，用户可在向导里改
DefaultDirName={autopf}\{#AppName}
DisableDirPage=no
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename={#AppName}-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 需求 D17：没有代码签名，杀软误报是预期内事件，下载页需给加白名单指引
PrivilegesRequired=admin

[Languages]
; 默认英文向导界面：Inno Setup 不自带简体中文，需自备 ChineseSimplified.isl
; 把它放进 Inno Setup 的 Languages 目录后，取消下面这行注释即可切成中文向导：
; Name: "chs"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
Source: "..\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked

[Run]
Filename: "{app}\{#AppExeName}"; Description: "立即启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 故意留空。卸载只删安装目录里的程序文件，用户数据一个字节都不动。
