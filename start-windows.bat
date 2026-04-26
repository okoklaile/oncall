@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ====================================
echo Starting SuperBizAgent Service
echo ====================================
echo.

REM Check if uv is installed (optional, pip will be used if not)
echo [1/6] Checking package manager...
where uv >nul 2>&1
if errorlevel 1 (
    echo [INFO] uv not installed, using traditional pip
    echo [TIP] Install uv to speed up: pip install uv
    set USE_UV=0
) else (
    echo [SUCCESS] uv package manager detected
    set USE_UV=1
)
echo.

REM Ensure correct Python version
echo [2/6] Configuring Python version...
if exist .python-version (
    set /p PYTHON_VERSION=<.python-version
    echo [INFO] Current configured version: !PYTHON_VERSION!
    
    REM Check if 3.10 (incompatible)
    echo !PYTHON_VERSION! | findstr /C:"3.10" >nul
    if not errorlevel 1 (
        echo [WARN] Python 3.10 is incompatible, auto-updating to 3.13...
        echo 3.13> .python-version
        echo [SUCCESS] Updated to Python 3.13
    )
) else (
    echo [INFO] Creating .python-version file...
    echo 3.13> .python-version
)
echo.

REM Create or sync virtual environment
echo [3/6] Creating/syncing virtual environment...
if exist .venv\Scripts\python.exe (
    echo [INFO] Virtual environment exists, checking for updates...
    
    REM If uv is available, try using uv sync
    if "%USE_UV%"=="1" (
        uv sync 2>nul
        if errorlevel 1 (
            echo [WARN] uv sync failed, using pip to update...
            .venv\Scripts\python.exe -m pip install -e . -q
        ) else (
            echo [SUCCESS] Synced using uv
        )
    ) else (
        echo [INFO] Using pip to update dependencies...
        .venv\Scripts\python.exe -m pip install -e . -q
    )
) else (
    echo [INFO] Creating new virtual environment...
    
    REM If uv is available, try using uv sync
    if "%USE_UV%"=="1" (
        echo [INFO] Trying to create using uv sync...
        uv sync 2>nul
        if not errorlevel 1 (
            echo [SUCCESS] Created using uv
            goto :venv_created
        )
        echo [WARN] uv sync failed, falling back to traditional method...
    )
    
    REM Create using traditional Python venv
    echo [INFO] Creating using python -m venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Virtual environment creation failed
        echo [TIP] Please ensure Python 3.11+ is installed
        pause
        exit /b 1
    )
    
    REM Install dependencies
    echo [INFO] Installing project dependencies (this may take a few minutes)...
    .venv\Scripts\python.exe -m pip install --upgrade pip -q
    .venv\Scripts\python.exe -m pip install -e . -q
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed
        pause
        exit /b 1
    )
    echo [SUCCESS] Virtual environment creation complete
)

:venv_created
echo [SUCCESS] Virtual environment ready
echo.

REM Set Python command
set PYTHON_CMD=.venv\Scripts\python.exe

REM Start Docker Compose
echo [4/6] Starting Milvus vector database...
docker ps --format "{{.Names}}" | findstr "milvus-standalone" >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Milvus container is already running
) else (
    docker compose -f vector-database.yml up -d
    if errorlevel 1 (
        echo [ERROR] Docker startup failed, please ensure Docker Desktop is running
        pause
        exit /b 1
    )
    echo [INFO] Waiting for Milvus to start (10 seconds)...
    timeout /t 10 /nobreak >nul
)
echo [SUCCESS] Milvus database ready
echo.

REM Start CLS MCP Service
echo [5/6] Starting CLS MCP Service...
start "CLS MCP Server" /min %PYTHON_CMD% mcp_servers/cls_server.py
timeout /t 2 /nobreak >nul
echo [SUCCESS] CLS MCP Service started
echo.

REM Start Monitor MCP Service
echo [6/6] Starting Monitor MCP Service...
start "Monitor MCP Server" /min %PYTHON_CMD% mcp_servers/monitor_server.py
timeout /t 2 /nobreak >nul
echo [SUCCESS] Monitor MCP Service started
echo.

REM Start FastAPI Service
echo [7/8] Starting FastAPI Service...
start "SuperBizAgent API" %PYTHON_CMD% -m uvicorn app.main:app --host 0.0.0.0 --port 9900
echo [INFO] Waiting for service to start (15 seconds)...
timeout /t 15 /nobreak >nul
echo.

REM Check service status and upload documents
echo.
echo [INFO] Checking service status...
curl -s http://localhost:9900/health >nul 2>&1
if errorlevel 1 (
    echo [WARN] Service might not be fully started, please wait a moment
) else (
    echo [SUCCESS] FastAPI service is running normally
    echo.
    
    REM Call API to upload aiops-docs documents to vector database
    echo [8/8] Uploading documents to vector database...
    for %%f in (aiops-docs\*.md) do (
        echo   Uploading: %%~nxf
        curl -s -X POST http://localhost:9900/api/upload -F "file=@%%f" >nul 2>&1
    )
    echo [SUCCESS] Document upload complete
)

echo.
echo ====================================
echo Service startup complete!
echo ====================================
echo Web Interface: http://localhost:9900
echo API Documentation: http://localhost:9900/docs
echo.
echo View logs:
echo   - FastAPI: logs\app_*.log (Loguru logs, daily rotation)
echo   - CLS MCP: type mcp_cls.log
echo   - Monitor: type mcp_monitor.log
echo Stop service: stop-windows.bat
echo ====================================
pause