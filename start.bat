@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

title AgentDrivenCompetBench

echo ============================================================
echo   AgentDrivenCompetBench - One Click Start (Windows)
echo ============================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.11+ not found
    echo   Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Check Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js 18+ not found
    echo   Download: https://nodejs.org/
    pause
    exit /b 1
)

:: Check .env — only create if missing, never overwrite existing
if not exist .env (
    if exist .env.reviewer (
        echo [INFO] Creating .env from .env.reviewer ...
        copy .env.reviewer .env >nul
    ) else (
        echo [WARN] No .env found, copying from .env.example ...
        copy .env.example .env >nul
        echo [WARN] Please edit .env with your API keys, then re-run
        notepad .env
        pause
        exit /b 1
    )
)

echo [1/4] Installing Python dependencies ...
pip install -e ".[dev]" -q
if errorlevel 1 (
    echo [ERROR] pip install failed
    pause
    exit /b 1
)

echo [2/4] Installing Playwright browser ...
playwright install chromium >nul 2>&1
echo        Chromium ready

echo [3/4] Installing frontend dependencies ...
cd frontend
call npm install --silent 2>nul
cd ..

echo [4/4] Starting services ...
echo.
echo   Backend:  http://localhost:8001
echo   Frontend: http://localhost:5173
echo.
echo ============================================================

:: Set project root (handle spaces in path)
set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

:: Start backend in visible window
start "Backend" /D "%PROJECT_DIR%" cmd /k "set PYTHONPATH=src && echo Starting backend http://localhost:8001 ... && python -m uvicorn api.app:app --host 0.0.0.0 --port 8001"

:: Wait for backend to be ready (up to 15s)
echo [INFO] Waiting for backend ...
set /a _wait=0
:wait_backend
timeout /t 2 /nobreak >nul
set /a _wait+=2
curl -s -o nul -w "" http://localhost:8001/docs >nul 2>&1
if errorlevel 1 (
    if %_wait% lss 15 goto wait_backend
    echo [WARN] Backend may not be ready yet, continuing anyway ...
) else (
    echo [INFO] Backend ready (%_wait%s)
)

:: Start frontend in visible window
start "Frontend" /D "%PROJECT_DIR%\frontend" cmd /k "echo Starting frontend http://localhost:5173 ... && npm run dev"

:: Wait and open browser
echo [INFO] Waiting for frontend (5s) ...
timeout /t 5 /nobreak >nul
start http://localhost:5173

echo.
echo Services started. Close the "Backend" and "Frontend" windows to stop.
pause
