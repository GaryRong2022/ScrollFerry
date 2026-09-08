#!/bin/bash
set -eu
cd "$(dirname "$0")"
for candidate in "$PWD/.venv/bin/python3" "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" python3; do
  if "$candidate" -c 'import tkinter, pdfplumber, pypdfium2' >/dev/null 2>&1; then
    "$candidate" -m pip install -r requirements-upload.txt
    echo '上传组件已安装。请安装 Google Chrome，然后重新启动 ScrollFerry。'
    read -r -p '按回车关闭…' _reply
    exit 0
  fi
done
echo '请先运行 start_mac.command，完成基础环境安装。'
read -r -p '按回车关闭…' _reply
