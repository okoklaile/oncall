# SuperBizAgent 启动脚本使用指南

## 🚀 快速启动

### 方法1：PowerShell 脚本（推荐）
```powershell
# 启动所有服务
.\start-all.ps1

# 停止所有服务
.\stop-all.ps1
```

### 方法2：批处理脚本
```batch
# 启动所有服务
.\start-all.bat

# 停止所有服务
.\stop-all.bat
```

## ⚙️ 高级选项

### PowerShell 版本的高级用法
```powershell
# 跳过 Docker 启动（如果数据库已运行）
.\start-all.ps1 -SkipDocker

# 不自动打开浏览器
.\start-all.ps1 -NoBrowser

# 组合使用
.\start-all.ps1 -SkipDocker -NoBrowser
```

## 📋 启动流程

脚本会按以下顺序启动服务：

1. ✅ 检查虚拟环境
2. ✅ 激活虚拟环境
3. ✅ 启动 Milvus 向量数据库（Docker）
4. ✅ 等待数据库启动（10秒）
5. ✅ 启动 MCP 服务（CLS + Monitor）
6. ✅ 启动 FastAPI 主服务
7. 🌐 自动打开浏览器

## 🔍 服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| Milvus 数据库 | 19530 | 向量数据库 |
| CLS MCP 服务 | 8003 | 日志查询服务 |
| Monitor MCP 服务 | 8004 | 监控数据服务 |
| FastAPI 后端 | 9900 | 主 API 服务 |
| 前端界面 | 9900 | Web 界面 |

## 🛑 停止服务

运行停止脚本或按 `Ctrl+C` 终止 PowerShell 脚本。

## 🔧 故障排除

### 问题：端口被占用
```powershell
# 查看占用端口的进程
netstat -ano | findstr :9900

# 杀死进程（替换 PID）
taskkill /PID 12345 /F
```

### 问题：Docker 未启动
```powershell
# 检查 Docker 服务
docker --version

# 启动 Docker Desktop
# 或手动启动数据库
docker compose -f vector-database.yml up -d
```

### 问题：虚拟环境不存在
```powershell
# 创建虚拟环境
python -m venv .venv

# 激活并安装依赖
.venv\Scripts\activate
pip install -e .
```

## 📝 日志位置

- 应用日志：`logs\app_YYYY-MM-DD.log`
- Docker 日志：`docker compose -f vector-database.yml logs`

## 💡 提示

- 首次运行需要等待较长时间（数据库初始化）
- 确保 Docker Desktop 已启动
- 如遇到权限问题，请以管理员身份运行 PowerShell