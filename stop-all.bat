@echo off
chcp 65001 >nul
echo =====================================
echo 🛑 SuperBizAgent 一键停止脚本 (BAT)
echo =====================================
echo.

REM 检查 PowerShell 是否可用
powershell -Command "Write-Host 'PowerShell 可用'" >nul 2>&1
if errorlevel 1 (
    echo ❌ PowerShell 不可用，请手动停止服务
    pause
    exit /b 1
)

REM 调用 PowerShell 脚本
echo 🔄 正在调用 PowerShell 停止脚本...
powershell -ExecutionPolicy Bypass -File "%~dp0stop-all.ps1"

if errorlevel 1 (
    echo ❌ 停止失败
) else (
    echo ✅ 停止完成
)

pause