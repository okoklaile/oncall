@echo off
chcp 65001 >nul
echo ====================================
echo Stopping SuperBizAgent Service
echo ====================================
echo.

REM Stop FastAPI Service
echo [1/4] Stopping FastAPI Service...
taskkill /FI "WINDOWTITLE eq SuperBizAgent API*" /F >nul 2>&1
if errorlevel 1 (
    echo [INFO] FastAPI Service is not running or already stopped
) else (
    echo [SUCCESS] FastAPI Service stopped
)
echo.

REM Stop CLS MCP Service
echo [2/4] Stopping CLS MCP Service...
taskkill /FI "WINDOWTITLE eq CLS MCP Server*" /F >nul 2>&1
if errorlevel 1 (
    echo [INFO] CLS MCP Service is not running or already stopped
) else (
    echo [SUCCESS] CLS MCP Service stopped
)
echo.

REM Stop Monitor MCP Service
echo [3/4] Stopping Monitor MCP Service...
taskkill /FI "WINDOWTITLE eq Monitor MCP Server*" /F >nul 2>&1
if errorlevel 1 (
    echo [INFO] Monitor MCP Service is not running or already stopped
) else (
    echo [SUCCESS] Monitor MCP Service stopped
)
echo.

REM Stop Docker containers
echo [4/4] Stopping Milvus container...
docker ps --format "{{.Names}}" | findstr "milvus" >nul 2>&1
if not errorlevel 1 (
    docker compose -f vector-database.yml down
    if errorlevel 1 (
        echo [ERROR] Failed to stop Docker container
    ) else (
        echo [SUCCESS] Milvus container stopped
    )
) else (
    echo [INFO] Milvus container is not running
)
echo.

echo ====================================
echo All services stopped!
echo ====================================
echo.
echo Tip:
echo   - To completely clean Docker volumes, run:
echo     docker compose -f vector-database.yml down -v
echo.
pause