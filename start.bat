@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AgentDrivenCompetBench - 一键启动

echo ============================================================
echo   AgentDrivenCompetBench 一键启动脚本 (Windows)
echo ============================================================
echo.

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] 未检测到 Python，请安装 Python 3.11+
    echo   下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 检查 Node.js
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] 未检测到 Node.js，请安装 Node.js 18+
    echo   下载地址: https://nodejs.org/
    pause
    exit /b 1
)

:: 检查 .env
if not exist .env (
    if exist .env.reviewer (
        echo [INFO] 使用预配置的 .env.reviewer...
        copy .env.reviewer .env >nul
    ) else (
        echo [WARN] 未找到 .env 文件，正在从 .env.example 复制...
        copy .env.example .env >nul
        echo [WARN] 请编辑 .env 文件填入 API 密钥后重新运行此脚本
        notepad .env
        pause
        exit /b 1
    )
)

echo [1/4] 安装 Python 依赖...
pip install -e ".[dev]" -q
if %errorlevel% neq 0 (
    echo [ERROR] pip install 失败
    pause
    exit /b 1
)

echo [2/4] 安装 Playwright 浏览器...
playwright install chromium >nul 2>&1
echo        Chromium 已就绪

echo [3/4] 安装前端依赖...
cd frontend
call npm install --silent 2>nul
cd ..

echo [4/4] 启动服务...
echo.
echo   后端: http://localhost:8001
echo   前端: http://localhost:5173
echo.
echo   按 Ctrl+C 停止所有服务
echo ============================================================

:: 启动后端（后台运行）
start /b cmd /c "set PYTHONPATH=src && python -m uvicorn api.app:app --host 0.0.0.0 --port 8001"

:: 等待后端就绪
timeout /t 3 /nobreak >nul

:: 启动前端（后台运行）
start /b cmd /c "cd frontend && npm run dev"

:: 等待前端就绪后打开浏览器
timeout /t 5 /nobreak >nul
start http://localhost:5173

:: 保持窗口打开
echo.
echo 服务已启动，浏览器已打开。关闭此窗口将停止所有服务。
pause >nul
