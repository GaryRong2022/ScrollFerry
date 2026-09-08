# Windows 安装程序构建

GitHub Actions 使用云端 Windows 运行 PyInstaller 和 Inno Setup；Mac 上准备代码即可，无需本地 Windows。当前仓库提供构建配置，尚未在 GitHub 实际运行构建。

1. 在 GitHub 创建代码仓库，将项目源码及 `.github/workflows/windows-installer.yml` 推送到默认分支。不要上传试卷、output、tmp、浏览器登录目录或虚拟环境。
2. 打开仓库 Actions → Build Windows installer → Run workflow。
3. 工作流运行本地测试、生成软件文件夹、制作安装 EXE，再执行静默安装与打包程序启动检查。
4. 成功后，在本次运行的 Artifacts 下载 `ScrollFerry-Windows-Installer-1.0.2`，解压得到 `ScrollFerry-Setup-1.0.2-x64.exe`。

安装向导支持选择目录、开始菜单和可选桌面快捷方式、卸载入口。默认安装到当前用户的 Programs 目录，不要求管理员权限。目标为 Windows 10/11 x64；当前安装向导使用 Inno Setup 自带英文界面，应用界面保持中文。本流程只产生下载附件，不自动发布 GitHub Release。

## 数据与浏览器

- Windows 运行数据：`%LOCALAPPDATA%\ScrollFerry`。
- macOS 运行数据：`~/Library/Application Support/ScrollFerry`。
- 登录状态分别位于 `browser-profiles/chrome`、`browser-profiles/msedge`；使用软件独立登录窗口，不接管日常浏览器个人资料。切换浏览器可能需要重新登录。
- 上传队列、上传图片副本及错误诊断位于 `batches/<批次路径摘要>`。旧导出目录的上传进度在首次读取时迁移，保留已上传及已保存状态，旧文件不删除。首次使用新的浏览器资料目录需要重新登录。
- 试卷、工程和导出截图仍保存到用户主动选择的位置。恢复上传时选择原导出目录的 manifest.json；请保持该目录位置不变。
- Windows 优先识别 HTTPS 默认浏览器：若为 Chrome 或 Edge 则优先启动，否则按 Chrome、Edge 顺序尝试。两者均不可用时提示安装任意一个。不会更改系统默认浏览器，也不会自动安装浏览器。
- 软件更新及卸载不会删除上述用户数据。

## 本地 Windows 构建

安装 Python 3.12 x64、Inno Setup 6，以及 Chrome 或 Edge，然后运行：

```powershell
python -m pip install -r requirements.txt -r requirements-upload.txt "pyinstaller>=6.11,<7" "reportlab>=4,<5"
powershell -ExecutionPolicy Bypass -File packaging/build.ps1
```

PyInstaller 包含 Python、Tk、PDFium、Pillow、Playwright 及其驱动，浏览器本体不打包。测试不使用小鹅通账号，不上传题目。

目前安装包未配置代码签名，Windows 首次运行可能显示发布者未验证提示。实际兼容性以 Windows 构建和安装测试结果为准。
