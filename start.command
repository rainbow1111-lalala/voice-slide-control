#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Double-click to launch Voice Slide Control / 双击启动语音翻页器
# First run sets up the environment automatically; instant afterwards.
# ─────────────────────────────────────────────────────────────
cd "$(dirname "$0")" || exit 1

echo "🎙  Voice Slide Control / 语音翻页器"
echo "──────────────────────────────────────"

# 1) Check Python
if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ Python 3 not found. Install it from https://www.python.org/downloads/ and double-click again."
  echo "   未找到 Python 3，请先安装后重试。"
  read -r -p "Press Enter to close… / 按回车关闭…"
  exit 1
fi

# 2) First run: create venv + install deps
if [ ! -d ".venv" ]; then
  echo "📦 First run: setting up (about 1-2 min, once only) / 首次启动，正在准备环境…"
  python3 -m venv .venv || { echo "❌ Failed to create venv / 创建环境失败"; read -r -p "Enter…"; exit 1; }
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt || { echo "❌ Failed to install deps (check network) / 安装依赖失败，请检查网络"; read -r -p "Enter…"; exit 1; }
  echo "✅ Ready / 环境就绪"
fi

# 3) Launch: open the browser, then run the server in the foreground
echo "🚀 Starting… opening http://127.0.0.1:5001 / 启动中，浏览器将自动打开"
echo "   Close this window to stop. / 关掉本窗口即停止。"
( sleep 2; open "http://127.0.0.1:5001" ) &
./.venv/bin/python app.py

echo ""
read -r -p "Stopped. Press Enter to close… / 已停止，按回车关闭…"
