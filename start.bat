@echo off
REM ─────────────────────────────────────────────────────────────
REM 双击我即可启动「语音翻页器」/ Double-click to launch Voice Slide Control
REM 首次运行会自动建立环境并安装依赖,之后秒开。
REM ─────────────────────────────────────────────────────────────
cd /d "%~dp0"
title Voice Slide Control

echo 语音翻页器 / Voice Slide Control
echo ----------------------------------------

REM 1) 检查 Python
where python >nul 2>nul
if errorlevel 1 (
  echo [X] 没找到 Python。请到 https://www.python.org/downloads/ 安装
  echo     安装时务必勾选 "Add Python to PATH",装好后重新双击本文件。
  pause
  exit /b 1
)

REM 2) 首次:建虚拟环境 + 装依赖
if not exist ".venv" (
  echo [*] 首次启动,正在准备运行环境(约 1-2 分钟,只此一次)...
  python -m venv .venv || (echo [X] 创建环境失败 & pause & exit /b 1)
  .venv\Scripts\python.exe -m pip install -q --upgrade pip
  .venv\Scripts\python.exe -m pip install -q -r requirements.txt || (echo [X] 安装依赖失败,请检查网络 & pause & exit /b 1)
  echo [OK] 环境就绪
)

REM 3) 启动:延迟打开浏览器,再前台运行服务
echo [*] 启动中... 浏览器会自动打开 http://127.0.0.1:5001
echo     (用完直接关掉这个窗口即可停止)
start "" cmd /c "timeout /t 3 >nul & explorer http://127.0.0.1:5001"
.venv\Scripts\python.exe app.py

echo.
echo 服务已停止。
pause
