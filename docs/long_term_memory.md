# 长期记忆系统

SuperBizAgent 的长期记忆分为两层：Milvus 向量库存放人工上传的知识文档，SQLite 存放 Agent 自动产出的诊断经验。两者职责分离，互不干扰。

## 1. 为什么分层

| | Milvus (知识库) | SQLite (经验记忆) |
|---|---|---|
| **数据来源** | 人工上传 .md/.txt | AIOps 诊断报告（运维确认后） |
| **数据特点** | 碎片化、需语义匹配 | 结构化、需精确过滤 |
| **检索方式** | 向量相似度 + BM25 + RRF | SQL WHERE + LIKE 关键词 |
| **检索场景** | "跟数据库连接池相关的内容" | "data-sync-service 的 CPU 告警上次怎么修的" |
| **source_type** | `"manual"` | `"aiops"` |

分层的原因：语义相似不等于同类告警。同样描述"CPU 高"的文档可能是完全不同的根因。经验记忆需要按服务名、告警类型、时间精确查询，SQLite 的 WHERE 条件比向量搜索更可控，且 AI 自产内容不会污染人工知识库。

## 2. 数据库设计

文件位置：`data/long_term_memory.db`（SQLite，WAL 模式）

### 2.1 aiops_memory 表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | 诊断ID，格式 `aiops-YYYYMMDD-HHMMSS-随机6位` |
| `input_text` | TEXT | 原始任务描述（截取前 500 字符） |
| `response` | TEXT | 诊断报告全文（Markdown） |
| `confirmed` | INTEGER | 1=运维确认修复成功，0=未确认/失败 |
| `source_type` | TEXT | 固定 `"aiops"` |
| `created_at` | TEXT | ISO 8601 时间戳（UTC+8） |

### 2.2 chat_memory 表（预留）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | 记忆ID |
| `content` | TEXT | 记忆内容 |
| `topic` | TEXT | 主题标签 |
| `session_id` | TEXT | 来源会话 ID |
| `source_type` | TEXT | 固定 `"chat"` |
| `created_at` | TEXT | ISO 8601 时间戳 |

chat_memory 表已建好，`store_chat()` / `search_chat()` 函数已实现，暂未接入触发逻辑。

## 3. 写入流程

```
用户点击"智能运维"
  → Planner → Executor → Replanner → 生成诊断报告 (SSE流式返回)
  → 前端渲染 Markdown + 弹出确认栏
  → 运维判断:
      ✅ "修复成功，存入经验库"
      ❌ "未修复，不存入"
  → POST /api/aiops/confirm { session_id, confirmed }
  → aiops_service.confirm_diagnosis() 读取 Redis checkpoint 中的 response
  → long_term_memory.store_aiops() 写入 SQLite
```

### 3.1 确认接口

```
POST /api/aiops/confirm
Content-Type: application/json

{
  "session_id": "session-xxx",
  "confirmed": true
}
```

响应：
```json
{"code": 200, "message": "诊断报告已写入长期记忆", "data": {"session_id": "...", "stored": true}}
```

### 3.2 关键代码路径

```
app/api/aiops.py              → POST /api/aiops/confirm
app/services/aiops_service.py → confirm_diagnosis()
app/agent/aiops/memory_store.py → store_aiops_memory()
app/services/long_term_memory.py → store_aiops() → SQLite INSERT
```

## 4. 检索

### 4.1 retrieve_past_diagnoses 工具

模型可通过 `retrieve_past_diagnoses` 工具检索历史诊断经验：

```
模型: retrieve_past_diagnoses("CPU 突增")
  → search_aiops(keyword="CPU 突增", confirmed_only=True, limit=3)
  → SQL: SELECT * FROM aiops_memory WHERE confirmed=1 AND (input_text LIKE '%CPU 突增%' OR response LIKE '%CPU 突增%') ORDER BY created_at DESC LIMIT 3
  → 返回格式化的历史案例（含完整诊断报告）
```

### 4.2 搜索结果格式

```
找到 2 条相关历史诊断经验：

---
### 历史案例 1
- 诊断ID: aiops-20260504-143052-a1b2c3
- 时间: 2026-05-04T14:30:52+08:00
- 任务描述: 诊断当前系统是否存在告警...

#### 诊断报告
# 告警分析报告
...
```

### 4.3 注册位置

`retrieve_past_diagnoses` 已注册到以下位置，所有场景均可调用：

| 位置 | 文件 |
|------|------|
| RAG Agent | `app/services/rag_agent_service.py:67` |
| AIOps Planner | `app/agent/aiops/planner.py:94` |
| AIOps Executor | `app/agent/aiops/executor1.py:74` |
| AIOps Replanner | `app/agent/aiops/replanner.py:143` |

## 5. 前端交互

AIOps 诊断完成后，报告底部出现确认栏：

```
┌─────────────────────────────────────────┐
│ 本次诊断是否成功解决了问题？              │
│ [修复成功，存入经验库] [未修复，不存入]   │
└─────────────────────────────────────────┘
```

- 点击任意按钮后禁用按钮（防止重复提交）
- 成功后显示绿色 "诊断报告已存入经验库"
- 实现代码：`static/app.js` 的 `showAIOpsConfirmation()` 和 `confirmAIOpsDiagnosis()`

## 6. 查看数据

SQLite 文件：`data/long_term_memory.db`

推荐 [DB Browser for SQLite](https://sqlitebrowser.org/) 可视化浏览。

或通过 Python 脚本：
```python
from app.services.long_term_memory import search_aiops, search_chat

# 查所有已确认的诊断
for r in search_aiops():
    print(r["id"], r["created_at"], len(r["response"]))

# 按关键词搜
for r in search_aiops("CPU"):
    print(r["response"][:500])
```
