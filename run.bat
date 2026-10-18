@echo off
chcp 65001 >nul
cd /d %~dp0

echo [1/3] 检查 Python 环境...
python --version
if errorlevel 1 (
  echo 找不到 Python，请先安装 Python 3.10 或更高版本：https://www.python.org/downloads/
  pause
  exit /b 1
)

echo [2/3] 准备依赖（第一次运行会慢一些，之后就快了）...
if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt

echo [3/3] 启动演示页面，浏览器会自动打开...
streamlit run src\ui\app.py

pause
