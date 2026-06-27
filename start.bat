@echo off
REM ─────────────────────────────────────────────────────────────
REM Double-click to launch Voice Slide Control / 双击启动语音翻页器
REM First run sets up the environment automatically; instant afterwards.
REM ─────────────────────────────────────────────────────────────
cd /d "%~dp0"
title Voice Slide Control

echo Voice Slide Control / 语音翻页器
echo ----------------------------------------

REM 1) Check Python
where python >nul 2>nul
if errorlevel 1 (
  echo [X] Python not found. Install from https://www.python.org/downloads/
  echo     Check "Add Python to PATH" during install, then double-click again.
  echo     未找到 Python，请安装时勾选 Add Python to PATH 后重试。
  pause
  exit /b 1
)

REM 2) First run: create venv + install deps
if not exist ".venv" (
  echo [*] First run: setting up (about 1-2 min, once) / 首次启动，正在准备环境...
  python -m venv .venv || (echo [X] venv failed / 创建环境失败 & pause & exit /b 1)
  .venv\Scripts\python.exe -m pip install -q --upgrade pip
  .venv\Scripts\python.exe -m pip install -q -r requirements.txt || (echo [X] install failed, check network / 安装依赖失败 & pause & exit /b 1)
  echo [OK] Ready / 环境就绪
)

REM 3) Launch: open the browser, then run the server in the foreground
echo [*] Starting... opening http://127.0.0.1:5001 / 启动中，浏览器将自动打开
echo     Close this window to stop. / 关掉本窗口即停止。
start "" cmd /c "timeout /t 3 >nul & explorer http://127.0.0.1:5001"
.venv\Scripts\python.exe app.py

echo.
echo Stopped. / 已停止。
pause
