#!/bin/bash
# ─────────────────────────────────────────────────────────────
# 双击我即可启动「语音翻页器」/ Double-click to launch Voice Slide Control
# 首次运行会自动建立环境并安装依赖,之后秒开。
# ─────────────────────────────────────────────────────────────
cd "$(dirname "$0")" || exit 1

echo "🎙  语音翻页器 / Voice Slide Control"
echo "──────────────────────────────────────"

# 1) 检查 Python
if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ 没找到 Python 3。请先到 https://www.python.org/downloads/ 安装,再双击本文件。"
  echo "   (装好后重试即可)"
  read -r -p "按回车键关闭…"
  exit 1
fi

# 2) 首次:建虚拟环境 + 装依赖
if [ ! -d ".venv" ]; then
  echo "📦 首次启动,正在准备运行环境(约 1-2 分钟,只此一次)…"
  python3 -m venv .venv || { echo "❌ 创建环境失败"; read -r -p "按回车关闭…"; exit 1; }
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt || { echo "❌ 安装依赖失败,请检查网络"; read -r -p "按回车关闭…"; exit 1; }
  echo "✅ 环境就绪"
fi

# 3) 启动:延迟打开浏览器,再前台运行服务
echo "🚀 启动中… 浏览器会自动打开 http://127.0.0.1:5001"
echo "   (用完直接关掉这个窗口即可停止)"
( sleep 2; open "http://127.0.0.1:5001" ) &
./.venv/bin/python app.py

echo ""
read -r -p "服务已停止。按回车键关闭窗口…"
