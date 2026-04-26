# View Real-time Logs Script
# Shows logs from all running services

Write-Host "====================================" -ForegroundColor Cyan
Write-Host "📋 SuperBizAgent Service Logs Viewer" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

# Check if services are running
$jobs = Get-Job | Where-Object { $_.Name -in @("CLS_MCP_Server", "Monitor_MCP_Server", "FastAPI_Server") }

if ($jobs.Count -eq 0) {
    Write-Host "No background services found. Services may not be running or were started with -ShowLogs." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "To start services with logs visible:" -ForegroundColor Cyan
    Write-Host "  .\start-all.ps1 -ShowLogs" -ForegroundColor White
    Write-Host ""
    Write-Host "To start services in background:" -ForegroundColor Cyan
    Write-Host "  .\start-all.ps1" -ForegroundColor White
    exit 1
}

Write-Host "Found $($jobs.Count) running services:" -ForegroundColor Green
foreach ($job in $jobs) {
    Write-Host "  • $($job.Name) - $($job.State)" -ForegroundColor White
}
Write-Host ""

# Show logs from each service
Write-Host "📄 Service Logs:" -ForegroundColor Cyan
Write-Host "----------------" -ForegroundColor Cyan

foreach ($job in $jobs) {
    Write-Host ""
    Write-Host "🔍 $($job.Name) Logs:" -ForegroundColor Yellow
    Write-Host "-------------------" -ForegroundColor Yellow

    try {
        $output = Receive-Job -Job $job -Keep
        if ($output) {
            $output | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }
        } else {
            Write-Host "  (No output yet)" -ForegroundColor DarkGray
        }
    } catch {
        Write-Host "  (Error reading logs: $($_.Exception.Message))" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "💡 Tips:" -ForegroundColor Cyan
Write-Host "  • This shows buffered output from background jobs" -ForegroundColor White
Write-Host "  • For real-time logs, use: .\start-all.ps1 -ShowLogs" -ForegroundColor White
Write-Host "  • Check log files: logs\app_$(Get-Date -Format 'yyyy-MM-dd').log" -ForegroundColor White
Write-Host "  • Stop services: .\stop-all.ps1" -ForegroundColor White