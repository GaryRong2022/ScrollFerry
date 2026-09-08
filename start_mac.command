#!/bin/bash
set -eu
cd "$(dirname "$0")"
mkdir -p tmp
launch_log="$PWD/tmp/mac-launch.log"
printf 'ScrollFerry startup\nHOME=%s\nproject=%s\n' "$HOME" "$PWD" > "$launch_log"

fail() {
  echo
  echo "$1"
  read -r -p "按回车关闭…" _reply
  exit 1
}

check_folder_permission() {
  if /usr/bin/grep -q 'Operation not permitted' "$launch_log"; then
    fail "macOS 拒绝访问项目文件夹，并非缺少 Python。
请打开 系统设置 → 隐私与安全性 → 文件与文件夹，
检查“终端”的“文稿文件夹”权限并允许访问，然后完全退出终端，再双击启动。
如果没有对应选项，请将 tmp/mac-launch.log 发给我继续排查。"
  fi
}

# Prefer an existing project environment, then the runtime available on this Mac.
bundled_python="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
for candidate in "$PWD/.venv/bin/python3" "$bundled_python" python3 python3.13 python3.12 python3.11; do
  printf '\nPython candidate: %s\n' "$candidate" >> "$launch_log"
  if "$candidate" -c 'import sys, tkinter, pdfplumber, pypdfium2; from PIL import ImageTk; assert sys.version_info >= (3, 11); print(sys.executable)' >> "$launch_log" 2>&1; then
    echo "正在启动 ScrollFerry…"
    "$candidate" -m scrollferry.app || fail "启动失败，请将上方错误信息发给我排查。"
    exit 0
  fi
done

check_folder_permission
echo "首次启动需要安装 PDF 处理依赖。"
python_bin=""
for candidate in python3 python3.13 python3.12 python3.11; do
  if "$candidate" -c 'import sys, tkinter; assert sys.version_info >= (3, 11)' >/dev/null 2>&1; then
    python_bin="$candidate"
    break
  fi
done
[ -n "$python_bin" ] || { cat "$launch_log"; fail "Python 启动检查失败，详细原因已保存到 tmp/mac-launch.log。"; }
"$python_bin" -m venv .venv || fail "无法创建 Python 环境。"
.venv/bin/python3 -m pip install -r requirements.txt || fail "依赖安装失败，请检查网络后重试。"
.venv/bin/python3 -m scrollferry.app || fail "启动失败，请将上方错误信息发给我排查。"
