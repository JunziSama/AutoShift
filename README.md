# AutoShift

Windows 10/11 64 位每秒点击左 Shift 工具，带中文置顶窗口、可配置全局热键和前台目标检查。

## 使用

1. 解压整个便携包，保留 AutoShift.exe 旁的 _internal 文件夹，双击 AutoShift.exe，按需同意管理员权限请求。
2. 打开目标程序，在 AutoShift 的窗口列表中选择对应窗口；目标后启动时可点“刷新”。
3. 切回目标窗口，按 **F8** 开启每秒点击；再按 F8 关闭，或按 **F9** 停止。
4. 也可点击“开始（三秒后）”，然后在三秒内切回目标窗口。
5. 切换到其他窗口或目标退出时会停止；返回目标后需要重新开启。
6. “热键设置”支持 F1–F11 与 Ctrl、Alt 组合；置顶可取消。设置会在下次启动时恢复，但运行状态永不恢复。

开启后立即点击一次；每次按下 50 毫秒后松开，后续按下间隔为一秒。
“每秒点击中”表示工具正在安排点击，不表示游戏一定接受输入；Windows 定时调度可能存在少量延迟。
运行期间不要同时手动按住 Shift；每次点击前检测到 Shift 已按下时，工具会停止。
若出现“释放未确认”，用停止按钮或停止热键重试；程序会保留窗口供重试。
正常退出会尝试释放。任务管理器强制结束、系统崩溃或输入桌面限制可能导致清理无法完成；
必要时手动按下并松开左 Shift，或注销当前 Windows 会话。

热键占用时会显示错误；可修改热键，程序在修改失败时尝试恢复原热键。
目标程序重新启动后，需要刷新并重新选择窗口。
只有目标前台时才会开启，不支持后台输入，也不会自动切回或激活目标窗口。

## 配置与日志

保存在当前用户的 %LOCALAPPDATA%\AutoShift，日志仅记录错误并限制大小。
删除 settings.json 可恢复默认设置。日志不包含键盘输入记录。
AUTOSHIFT_DATA_DIR 仅用于测试或指定独立配置目录。

## 从源码运行与构建

使用带 Tkinter 的 Python 3.12 或更新兼容版本，在项目目录中执行：

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe main.py
.\build.ps1
~~~

源码运行不会自动提权；需测试高权限目标时，在管理员终端启动。
构建产物为 dist\AutoShift\AutoShift.exe 及 dist\AutoShift-1.1.0-win64.zip。
已存在的发布压缩包不会被构建脚本覆盖。

## 测试

~~~powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe tests\native_smoke.py
~~~

原生测试仅操作测试程序自建的窗口和模拟输入；测试前松开 Shift，不要在测试期间操作键盘。
验证结果保存在 .test-data，实际游戏行为需另行确认。

## 边界

本程序使用普通 Windows 输入 API，不包含 NEAC 反检测、隐藏程序、驱动或绕过脚本限制。
管理员权限不保证输入被目标接受，也不保证每秒点击 Shift 能防止游戏判定挂机。

## 开源许可

Copyright (C) 2026 JunziSama。
本项目源码采用 [GNU GPL v3.0（仅此版本）](LICENSE) 发布，SPDX 标识为 `GPL-3.0-only`。
你可以按照许可证使用、修改和再分发源码；再分发时请保留版权和许可声明，并遵守 GPL v3.0 的对应源码要求。

Windows 便携包发布在 GitHub Releases；源码可按上文步骤构建。
便携包使用 Windows 模拟输入 API，不保证目标程序接受点击，也不包含任何反检测或绕过脚本限制功能。
