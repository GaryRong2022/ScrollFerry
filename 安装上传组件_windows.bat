@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo 请先运行 start_windows.bat，完成基础环境安装。
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m pip install -r requirements-upload.txt
if errorlevel 1 (
  echo 安装失败，请检查网络后重试。
) else (
  echo 上传组件已安装。请安装 Google Chrome，然后重新启动 ScrollFerry。
)
pause
