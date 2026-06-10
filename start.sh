#!/usr/bin/env bash
set -e

echo "============================================================"
echo "  AgentDrivenCompetBench 一键启动脚本 (macOS / Linux)"
echo "============================================================"
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] 未检测到 Python3，请安装 Python 3.11+"
    echo "  macOS: brew install python@3.11"
    echo "  Ubuntu: sudo apt install python3.11 python3.11-venv"
    exit 1
fi

# 检查 Node.js
if ! command -v node &> /dev/null; then
    echo "[ERROR] 未检测到 Node.js，请安装 Node.js 18+"
    echo "  macOS: brew install node"
    echo "  Ubuntu: curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash - && sudo apt install nodejs"
    exit 1
fi

# 检查 .env
if [ ! -f .env ]; then
    if [ -f .env.reviewer ]; then
        echo "[INFO] 使用预配置的 .env.reviewer..."
        cp .env.reviewer .env
    else
        echo "[WARN] 未找到 .env 文件，正在从 .env.example 复制..."
        cp .env.example .env
        echo "[WARN] 请编辑 .env 文件填入 API 密钥后重新运行此脚本"
        echo "  运行: nano .env 或 vim .env"
        exit 1
    fi
fi

echo "[1/4] 安装 Python 依赖..."
pip3 install -e ".[dev]" -q

echo "[2/4] 安装 Playwright 浏览器..."
python3 -m playwright install chromium > /dev/null 2>&1
echo "       Chromium 已就绪"

echo "[3/4] 安装前端依赖..."
cd frontend && npm install --silent 2>/dev/null && cd ..

echo "[4/4] 启动服务..."
echo ""
echo "  后端: http://localhost:8000"
echo "  前端: http://localhost:5173"
echo ""
echo "  按 Ctrl+C 停止所有服务"
echo "============================================================"

# 清理函数：退出时杀掉子进程
cleanup() {
    echo ""
    echo "正在停止服务..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

# 启动后端
PYTHONPATH=src python3 -m uvicorn api.app:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# 等待后端就绪
sleep 3

# 启动前端
cd frontend && npm run dev &
FRONTEND_PID=$!
cd ..

# 等待前端就绪后打开浏览器
sleep 5
if command -v open &> /dev/null; then
    open http://localhost:5173
elif command -v xdg-open &> /dev/null; then
    xdg-open http://localhost:5173
fi

echo ""
echo "服务已启动，浏览器已打开。按 Ctrl+C 停止所有服务。"

# 等待子进程
wait
