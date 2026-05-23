# 答辩演示启动脚本
# 关键点：不使用 --reload，避免 WatchFiles 重启导致模块级 _task_traces 被清空
#       （后果：前端 Agent 调用链面板会显示空，traces 数=0）
#
# 用法：
#   pwsh scripts/demo_start.ps1
#
# 启动后：
#   后端 → http://localhost:8001 (API + SSE)
#   前端 → http://localhost:5173 (Vue 3)

$ErrorActionPreference = "Stop"

Write-Host "=== AgentDrivenCompetBench 演示模式 ===" -ForegroundColor Cyan
Write-Host ""

# 检查 .env
if (-not (Test-Path ".env")) {
    Write-Host "[ERROR] 未找到 .env 文件，请先复制 .env.example 并填入 API 密钥" -ForegroundColor Red
    exit 1
}

# 检查关键环境变量
$envContent = Get-Content ".env" -Raw
$missing = @()
foreach ($key in @("ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "LANGFUSE_SECRET_KEY")) {
    if ($envContent -notmatch "$key=\S+") {
        $missing += $key
    }
}
if ($missing.Count -gt 0) {
    Write-Host "[WARN] .env 中以下密钥可能缺失: $($missing -join ', ')" -ForegroundColor Yellow
}

# 启动后端（无 --reload）
Write-Host "[1/2] 启动后端 uvicorn (无 --reload，保证 agent_traces 不丢失)..." -ForegroundColor Green
$backend = Start-Process -FilePath "uvicorn" `
    -ArgumentList "src.api.app:app", "--host", "0.0.0.0", "--port", "8001" `
    -PassThru -WindowStyle Normal

Start-Sleep -Seconds 3

# 启动前端
Write-Host "[2/2] 启动前端 vite dev server..." -ForegroundColor Green
Push-Location frontend
$frontend = Start-Process -FilePath "npm" `
    -ArgumentList "run", "dev" `
    -PassThru -WindowStyle Normal
Pop-Location

Start-Sleep -Seconds 2

Write-Host ""
Write-Host "=== 启动完成 ===" -ForegroundColor Cyan
Write-Host "后端 PID: $($backend.Id)  → http://localhost:8001"
Write-Host "前端 PID: $($frontend.Id)  → http://localhost:5173"
Write-Host ""
Write-Host "停止：在两个新开的窗口中按 Ctrl+C，或执行：" -ForegroundColor Yellow
Write-Host "  Stop-Process -Id $($backend.Id), $($frontend.Id) -Force"
