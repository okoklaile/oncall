@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo =====================================
echo 🚀 SuperBizAgent 一键启动脚本 (BAT)
echo =====================================
echo.

REM 检查 PowerShell 是否可用
powershell -Command "Write-Host 'PowerShell 可用'" >nul 2>&1
if errorlevel 1 (
    echo ❌ PowerShell 不可用，请使用 PowerShell 版本: .\start-all.ps1
    pause
    exit /b 1
)

REM 调用 PowerShell 脚本
echo 🔄 正在启动 PowerShell 启动脚本...
powershell -ExecutionPolicy Bypass -File "%~dp0start-all.ps1" %*

if errorlevel 1 (
    echo ❌ 启动失败
    pause
) else (
    echo ✅ 启动完成
)

pause