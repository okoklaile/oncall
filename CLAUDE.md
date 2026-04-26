# SuperBizAgent

Python 3.11+ 企业级智能对话与运维助手，基于 FastAPI + LangChain + LangGraph + LangChain-QWQ，使用阿里云 DashScope (Qwen) 作为 LLM，Milvus 作为向量数据库，MCP 协议集成工具。

## 环境

| 项目 | 说明 |
|------|------|
| Python | 3.11 - 3.13 |
| 包管理 | `uv` (推荐) + `uv.lock`，兼容 pip |
| 虚拟环境 | `.venv/` |
| 关键依赖 | fastapi, langchain, langgraph, langchain_qwq, pymilvus, dashscope, langchain_mcp_adapters |

## 常用命令

```bash
make init      # 一键初始化：启动 Docker → 启动服务 → 上传文档
make start     # 启动全部服务 (CLS-MCP + Monitor-MCP + FastAPI)
make stop      # 停止全部服务
make dev       # 开发模式 (热重载, 前台)
make run       # 生产模式 (前台)
make check     # 健康检查
make test      # 运行测试 + 覆盖率
make format    # ruff 格式化
make upload    # 上传 aiops-docs/ 文档到向量库
make clean     # 清理缓存文件
```

Windows 下用 `.\start-all.ps1` / `.\stop-all.ps1`。

## 项目结构

```
app/
├── main.py                  # FastAPI 入口，lifespan 管理 Milvus 连接
├── config.py                # Pydantic Settings 配置 (.env)
├── api/                     # 路由
│   ├── chat.py              # POST /api/chat, /api/chat_stream (SSE)
│   ├── aiops.py             # POST /api/aiops (流式诊断)
│   ├── file.py              # POST /api/upload, /api/index_directory
│   └── health.py            # GET /health
├── services/                # 业务逻辑
│   ├── rag_agent_service.py       # LangGraph RAG Agent (ChatQwen 原生)
│   ├── aiops_service.py           # Plan-Execute-Replan 诊断流程
│   ├── vector_store_manager.py    # Milvus 向量库写入
│   ├── vector_embedding_service.py # DashScope Embeddings (langchain 标准接口)
│   ├── vector_search_service.py   # Milvus ANN 检索
│   ├── vector_index_service.py    # 索引编排：读文件→分块→入库
│   ├── document_splitter_service.py # 文档分块
│   └── rerank_service.py          # DashScope gte-rerank 精排
├── agent/
│   ├── mcp_client.py        # MCP 客户端 (langchain_mcp_adapters)，含重试拦截器
│   └── aiops/               # Plan-Execute-Replan 节点
│       ├── planner.py       # 计划生成
│       ├── executor1.py     # 步骤执行 (当前使用)
│       ├── replanner.py     # 计划调整
│       └── state.py         # PlanExecuteState 定义
├── core/
│   ├── milvus_client.py     # Milvus 连接管理 + BM25 混合索引
│   └── llm_factory.py       # LLM 工厂
├── models/                  # Pydantic 请求/响应模型
├── tools/                   # Agent 内置工具
│   ├── knowledge_tool.py    # 知识库检索
│   └── time_tool.py         # 当前时间
└── utils/logger.py          # Loguru 日志

mcp_servers/
├── cls_server.py            # 日志查询 MCP 服务 (port 8003)
└── monitor_server.py        # 监控数据 MCP 服务 (port 8004)

static/                      # 前端页面 (index.html + app.js + styles.css)
tests/                       # pytest 测试
aiops-docs/                  # 知识库文档源文件
```

## 架构要点

### LLM
- 使用 `langchain_qwq.ChatQwen` (DashScope OpenAI 兼容模式)
- 默认模型 `qwen-max`，需配置 `DASHSCOPE_API_KEY`
- Embedding: `text-embedding-v4` (1024 维)，Rerank: `gte-rerank`

### Milvus (向量数据库)
- Collection: `biz`，端口 19530，Docker 部署
- **混合检索**: 稠密向量 (1024维, HNSW/COSINE) + BM25 稀疏向量 (SPARSE_WAND)
- BM25 通过 `FunctionType.BM25` 自动从 `content` 字段生成 `sparse_vector`
- Schema 自动升级：检测到缺少 sparse_vector 或维度不匹配时会重建

### RAG Agent (LangGraph)
- 用 `langchain.agents.create_agent` 创建，自带 SummarizationMiddleware
- 消息历史修剪：保留首条 system message + 最近 6 条
- Redis checkpointer (`AsyncRedisSaver`) 持久化会话，Redis 端口 16379
- 工具：`retrieve_knowledge` + `get_current_time` + MCP 工具

### AIOps (Plan-Execute-Replan)
- 三节点图：Planner → Executor → Replanner (条件循环)
- Replanner 判断是否继续执行或生成最终报告
- 输出格式为 markdown 诊断报告

### MCP 集成
- 使用 `langchain_mcp_adapters` 的 `MultiServerMCPClient`
- 全局单例，工具调用失败时自动重试 (指数退避，最多 3 次)
- Streamable HTTP 传输，运行在独立进程中

### 配置 (.env)
| 变量 | 默认值 | 说明 |
|------|--------|------|
| DASHSCOPE_API_KEY | (必填) | 阿里云 DashScope API Key |
| DASHSCOPE_MODEL | qwen-max | 主模型 |
| RAG_TOP_K | 3 | 检索结果数 |
| MILVUS_HOST/PORT | localhost:19530 | Milvus 地址 |
| REDIS_URL | redis://localhost:16379 | 会话持久化 |
| MCP_CLS_URL | http://localhost:8003/mcp | CLS MCP 地址 |
| MCP_MONITOR_URL | http://localhost:8004/mcp | Monitor MCP 地址 |

## API 端点

- `GET /health` — 健康检查
- `POST /api/chat` — 一次性对话
- `POST /api/chat_stream` — SSE 流式对话
- `POST /api/chat/clear` — 清空会话
- `GET /api/chat/session/{id}` — 查询会话历史
- `POST /api/aiops` — AIOps 流式诊断
- `POST /api/upload` — 上传文件并自动索引
- `POST /api/index_directory` — 索引目录
- Web UI: `http://localhost:9900` | API 文档: `http://localhost:9900/docs`

## 开发约定

- **格式**: ruff (line-length=100)，禁用 E501/B008/C901
- **类型检查**: mypy (宽松模式，忽略缺失 import)
- **测试**: pytest + pytest-asyncio + pytest-cov, tests/
- **日志**: Loguru，见 `app/utils/logger.py`
- 全局单例服务首次使用时自动初始化 (`rag_agent_service`, `aiops_service` 等)
