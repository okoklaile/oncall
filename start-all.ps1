# SuperBizAgent One-Click Startup Script
# Automatically start all services: database, MCP services, backend API, frontend webpage
#
# Usage:
#   .\start-all.ps1                    # Start all services in background
#   .\start-all.ps1 -ShowLogs          # Start services sequentially to show logs
#   .\start-all.ps1 -SkipDocker        # Skip Docker database startup
#   .\start-all.ps1 -NoBrowser         # Don't open browser automatically
#   .\start-all.ps1 -ShowLogs -NoBrowser  # Show logs but don't open browser

param(
    [switch]$NoBrowser,  # Do not automatically open browser
    [switch]$SkipDocker, # Skip Docker startup
    [switch]$ShowLogs    # Show real-time logs from all services
)

Write-Host "====================================" -ForegroundColor Cyan
Write-Host "🚀 SuperBizAgent One-Click Startup Script" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

# Check virtual environment
Write-Host "[1/6] Checking virtual environment..." -ForegroundColor Yellow
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "❌ Virtual environment does not exist, please run installation script first" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Virtual environment exists" -ForegroundColor Green

# Activate virtual environment
Write-Host "[2/6] Activating virtual environment..." -ForegroundColor Yellow
try {
    . ".venv\Scripts\Activate.ps1"
} catch {
    Write-Host "❌ Virtual environment activation failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Virtual environment activated" -ForegroundColor Green

# Start Docker database (if not skipped)
if (-not $SkipDocker) {
    Write-Host "[3/6] Starting Milvus vector database..." -ForegroundColor Yellow
    docker compose -f vector-database.yml up -d
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Docker startup failed, please check if Docker is installed and running" -ForegroundColor Red
        exit 1
    }
    Write-Host "✅ Milvus database starting..." -ForegroundColor Green

    # Wait for database startup
    Write-Host "[4/6] Waiting for database startup (10 seconds)..." -ForegroundColor Yellow
    Start-Sleep -Seconds 10
    Write-Host "✅ Database startup completed" -ForegroundColor Green
} else {
    Write-Host "[3/6] ⏭️  Skipping Docker startup" -ForegroundColor Blue
    Write-Host "[4/6] ⏭️  Skipping wait time" -ForegroundColor Blue
}

# Start MCP services
Write-Host "[5/6] Starting MCP services..." -ForegroundColor Yellow

if ($ShowLogs) {
    # Start services sequentially to show logs
    Write-Host "  └─ Starting CLS log service..." -ForegroundColor Gray
    Write-Host "    (Press Ctrl+C to stop and continue to next service)" -ForegroundColor DarkGray
    try {
        & ".venv\Scripts\python.exe" "mcp_servers/cls_server.py"
    } catch {
        Write-Host "CLS service stopped or failed" -ForegroundColor Yellow
    }

    Write-Host "  └─ Starting Monitor monitoring service..." -ForegroundColor Gray
    Write-Host "    (Press Ctrl+C to stop and continue to next service)" -ForegroundColor DarkGray
    try {
        & ".venv\Scripts\python.exe" "mcp_servers/monitor_server.py"
    } catch {
        Write-Host "Monitor service stopped or failed" -ForegroundColor Yellow
    }

    Write-Host "✅ MCP services startup completed" -ForegroundColor Green

    # Start FastAPI main service
    Write-Host "[6/6] Starting FastAPI main service..." -ForegroundColor Yellow
    Write-Host "    (This will run in foreground. Press Ctrl+C to stop all services)" -ForegroundColor DarkGray
    try {
        & ".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 9900
    } catch {
        Write-Host "FastAPI service stopped" -ForegroundColor Yellow
    }
} else {
    # Start services in background (original behavior)
    Write-Host "  └─ Starting CLS log service..." -ForegroundColor Gray
    $clsJob = Start-Job -ScriptBlock {
        Set-Location $using:PWD
        & ".venv\Scripts\python.exe" "mcp_servers/cls_server.py"
    } -Name "CLS_MCP_Server"

    Write-Host "  └─ Starting Monitor monitoring service..." -ForegroundColor Gray
    $monitorJob = Start-Job -ScriptBlock {
        Set-Location $using:PWD
        & ".venv\Scripts\python.exe" "mcp_servers/monitor_server.py"
    } -Name "Monitor_MCP_Server"

    # Wait for MCP services startup
    Start-Sleep -Seconds 3
    Write-Host "✅ MCP services startup completed" -ForegroundColor Green

    # Start FastAPI main service (background)
    Write-Host "[6/6] Starting FastAPI main service..." -ForegroundColor Yellow
    $apiJob = Start-Job -ScriptBlock {
        Set-Location $using:PWD
        & ".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 9900
    } -Name "FastAPI_Server"

    # Wait for API service startup
    Start-Sleep -Seconds 5
    Write-Host "✅ FastAPI service startup completed" -ForegroundColor Green
}

Write-Host ""
Write-Host "====================================" -ForegroundColor Green
Write-Host "🎉 All services started successfully!" -ForegroundColor Green
Write-Host "====================================" -ForegroundColor Green
Write-Host ""
Write-Host "📊 Service Status:" -ForegroundColor Cyan
Write-Host "  • Milvus Database: http://localhost:19530" -ForegroundColor White
Write-Host "  • CLS MCP Service: http://localhost:8003/mcp" -ForegroundColor White
Write-Host "  • Monitor MCP Service: http://localhost:8004/mcp" -ForegroundColor White
Write-Host "  • FastAPI Backend: http://localhost:9900" -ForegroundColor White
Write-Host "  • API Docs: http://localhost:9900/docs" -ForegroundColor White
Write-Host "  • Frontend Interface: http://localhost:9900" -ForegroundColor White
Write-Host ""

# Open browser
if (-not $NoBrowser) {
    Write-Host "🌐 Opening frontend webpage..." -ForegroundColor Yellow
    try {
        Start-Process "http://localhost:9900"
        Write-Host "✅ Browser opened" -ForegroundColor Green
    } catch {
        Write-Host "⚠️  Browser open failed, please manually visit http://localhost:9900" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "💡 Tips:" -ForegroundColor Cyan
if ($ShowLogs) {
    Write-Host "  • Services are running in foreground mode" -ForegroundColor White
    Write-Host "  • Press Ctrl+C in each service window to stop" -ForegroundColor White
} else {
    Write-Host "  • Press Ctrl+C to stop all services" -ForegroundColor White
}
Write-Host "  • View logs: logs\app_$(Get-Date -Format 'yyyy-MM-dd').log" -ForegroundColor White
Write-Host "  • Stop services: .\stop-all.ps1" -ForegroundColor White
if (-not $ShowLogs) {
    Write-Host "  • Show live logs: .\start-all.ps1 -ShowLogs" -ForegroundColor White
}
Write-Host ""

if ($ShowLogs) {
    Write-Host "All services have been started in sequence. Check above for any startup logs." -ForegroundColor Green
    exit 0
}

# Keep script running, display service status
Write-Host "🔄 Services running... (Press Ctrl+C to exit)" -ForegroundColor Gray
Write-Host ""

# Monitor service status
while ($true) {
    try {
        # Check running status of each service
        $jobs = Get-Job | Where-Object { $_.Name -in @("CLS_MCP_Server", "Monitor_MCP_Server", "FastAPI_Server") }

        foreach ($job in $jobs) {
            if ($job.State -eq "Failed") {
                Write-Host "[ERROR] Service $($job.Name) failed" -ForegroundColor Red
            }
        }

        Start-Sleep -Seconds 5
    } catch {
        break
    }
}

# Clean up jobs
Write-Host ""
Write-Host "🧹 Cleaning up background tasks..." -ForegroundColor Yellow
Get-Job | Where-Object { $_.Name -in @("CLS_MCP_Server", "Monitor_MCP_Server", "FastAPI_Server") } | Remove-Job -Force
Write-Host "✅ Cleanup completed" -ForegroundColor Green