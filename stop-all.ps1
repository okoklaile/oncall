# SuperBizAgent 一键停止脚本
# 停止所有服务：前端、后端、MCP服务、数据库

Write-Host "====================================" -ForegroundColor Cyan
Write-Host "🛑 SuperBizAgent 一键停止脚本" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

# 停止后台作业
Write-Host "[1/4] 停止后台 PowerShell 作业..." -ForegroundColor Yellow
$jobs = Get-Job | Where-Object { $_.Name -in @("CLS_MCP_Server", "Monitor_MCP_Server", "FastAPI_Server") }
if ($jobs) {
    $jobs | Stop-Job -PassThru | Remove-Job
    Write-Host "✅ 后台作业已停止" -ForegroundColor Green
} else {
    Write-Host "ℹ️  没有找到后台作业" -ForegroundColor Blue
}

# 停止进程
Write-Host "[2/4] 停止相关进程..." -ForegroundColor Yellow

# 停止 Python 进程
$pythonProcesses = Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like "*uvicorn*" -or
    $_.CommandLine -like "*cls_server.py*" -or
    $_.CommandLine -like "*monitor_server.py*"
}

if ($pythonProcesses) {
    $pythonProcesses | ForEach-Object {
        Write-Host "  └─ 停止进程: $($_.ProcessName) (PID: $($_.Id))" -ForegroundColor Gray
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "✅ Python 进程已停止" -ForegroundColor Green
} else {
    Write-Host "ℹ️  没有找到相关 Python 进程" -ForegroundColor Blue
}

# 停止 Docker 容器
Write-Host "[3/4] 停止 Docker 容器..." -ForegroundColor Yellow
try {
    docker compose -f vector-database.yml down
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Docker 容器已停止" -ForegroundColor Green
    } else {
        Write-Host "⚠️  Docker 停止可能有问题，请手动检查" -ForegroundColor Yellow
    }
} catch {
    Write-Host "ℹ️  Docker 未运行或不可用" -ForegroundColor Blue
}

# 清理可能残留的进程
Write-Host "[4/4] 清理残留进程..." -ForegroundColor Yellow
$leftoverProcesses = Get-Process | Where-Object {
    $_.ProcessName -eq "python" -and (
        $_.CommandLine -like "*mcp_servers*" -or
        $_.CommandLine -like "*uvicorn*"
    )
} -ErrorAction SilentlyContinue

if ($leftoverProcesses) {
    $leftoverProcesses | ForEach-Object {
        Write-Host "  └─ 清理残留进程: $($_.ProcessName) (PID: $($_.Id))" -ForegroundColor Gray
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "✅ 残留进程已清理" -ForegroundColor Green
} else {
    Write-Host "ℹ️  没有发现残留进程" -ForegroundColor Blue
}

Write-Host ""
Write-Host "====================================" -ForegroundColor Green
Write-Host "✅ 所有服务已停止！" -ForegroundColor Green
Write-Host "====================================" -ForegroundColor Green
Write-Host ""
Write-Host "💡 提示：" -ForegroundColor Cyan
Write-Host "  • 如需重启: .\start-all.ps1" -ForegroundColor White
Write-Host "  • 查看日志: logs\ 目录" -ForegroundColor White
Write-Host "  • 检查端口: netstat -ano | findstr :9900" -ForegroundColor White