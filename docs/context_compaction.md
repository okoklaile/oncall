# 上下文压缩管理

基于 Claude Code 三层压缩架构实现。核心思想：**压缩不是删除历史，而是把细节挤掉，让模型在有限 token 预算内保持最大决策能力。**

## 1. 背景

Agent 的上下文主要在工具调用中膨胀。一轮典型交互中，用户消息和模型思考可能只占 10%，工具返回结果占 90%。`search_log` 一次返回数千字符的日志，`retrieve_knowledge` 返回长篇文档片段——这些都会在后续轮次中持续占据上下文空间，即使模型早已消化完它们的语义。

## 2. 三层压缩架构

```
工具输出
  │
  ├── 太长 ──→ Layer1: 全量写入磁盘，上下文留预览+路径
  │
  ▼
消息列表
  │
  ├── 工具结果太多 ──→ Layer2: 旧结果替换为占位符，只保留最近3条
  │
  ▼
整体仍超限
  │
  └── Layer3: 整段历史 → LLM 摘要
```

### 2.1 Layer1 — 大输出落盘

**触发条件**：ToolMessage 内容 > 8000 字符（约 2000 tokens）

**操作**：
1. 全量内容写入 `.task_outputs/{tool_call_id}.txt`
2. 消息内容替换为 `<persisted-output>` XML 标记 + 前 2000 字符预览

**效果**：一条 15000 字的工具输出从占 15000 字符 → 占 ~300 字符。

**XML 格式**：
```xml
<persisted-output>
tool: search_log
file: .task_outputs/call_abc123.txt
preview (2000/15000 chars):
[前 2000 字符内容...]
</persisted-output>
```

模型知道完整内容在哪，需要时可以提示用户查看或再次读取。

### 2.2 Layer2 — 微压缩（工具结果占位）

**触发条件**：ToolMessage 数量 > 3

**操作**：
- 保留最后 3 条工具结果原文
- 更早的全部替换为 `[Earlier tool result: {tool_name} — omitted for brevity]`

**设计原理**：模型早已在"当时那轮对话"中消化过旧工具结果。5 轮前的日志原文留着原文只是在吃 token。但最后 3 条结果保留原文——因为当前步骤可能仍在引用它们。

### 2.3 Layer3 — 摘要压缩

**触发条件**：Layer1 + Layer2 执行后，上下文仍超过 48000 字符（约 12000 tokens），或手动 force

**操作**：
1. 将所有消息拼接为对话文本（ToolMessage 只取前 300 字）
2. 调用 summary model（ChatQwen, temperature=0）生成摘要
3. 全部历史替换为一条 `[Compacted]\n{summary}` 消息

**摘要 Prompt 要求保留的信息**：
- 用户任务目标
- 已完成的步骤和结论
- 使用的工具名称
- 涉及的文件路径或数据源
- 未解决的关键问题

### 2.4 阈值配置

| 常量 | 值 | 说明 |
|------|-----|------|
| `PERSIST_THRESHOLD` | 8000 字符 | 工具输出超过此值触发落盘 |
| `MICRO_KEEP_LAST` | 3 | 微压缩保留最近 N 条工具结果原文 |
| `CONTEXT_CHAR_LIMIT` | 48000 字符 | 上下文超过此值触发摘要（≈12000 tokens） |

文件位置：`app/services/context_compactor.py`

## 3. 图结构

压缩不在 middleware 中，而是作为显式节点嵌入 Agent 循环。

### 3.1 RAG Agent 图

```
agent → (有tool_calls) → tools → compact → agent
agent → (无tool_calls) → END
```

```
                    ┌──────────────────────┐
                    │     compact_node       │
                    │                       │
  tools ──────────→ │  Layer1: 大输出→磁盘   │
  (ToolMessages)    │  Layer2: 旧结果→占位   │
                    │  Layer3: 超限→摘要     │
                    │                       │
                    └──────────┬────────────┘
                               │
                               ▼
                            agent
```

实现文件：`app/services/rag_agent_service.py` 的 `_ensure_graph()`

### 3.2 AIOps Executor 图

```
agent → (有tool_calls) → tools → compact → agent
agent → (无tool_calls) → END
```

结构同 RAG Agent，compact_node 复用 Executor 自己的 ChatQwen(temperature=0) 作为摘要模型。

实现文件：`app/agent/aiops/executor1.py`

### 3.3 执行策略

| 层 | 何时执行 | 成本 | 日志 |
|---|---------|------|------|
| Layer1 | 每次工具调用后 | 纯文本，无 LLM | `Layer1: persisted output, tool=xxx` |
| Layer2 | 每次工具调用后 | 纯文本，无 LLM | `Layer2: micro compacted N tool results` |
| Layer3 | 仅在前两层无效或手动 | 一次 LLM 调用 | `Layer3: summary compact applied` |

Layer1 和 Layer2 总是执行（成本为零），Layer3 按需触发。每次 compact 结束时输出汇总日志：

```
# 有压缩时:
Compact: 52000 -> 12000 chars (-77%), layers=[1, 2, 3]

# 无压缩时:
Compact: no action needed, 3500 chars, layers=[1, 2]
```

## 4. 与旧方案的对比

| | 旧方案 | 新方案 |
|---|--------|--------|
| 压缩位置 | `SummarizationMiddleware` 黑盒 | 图中显式 compact_node |
| 大输出处理 | 无，原样带跑 | Layer1 落盘 |
| 旧工具结果 | 无专门处理 | Layer2 占位符 |
| 历史摘要 | token>12000 整体压 | Layer3，但数据已被前两层"瘦身" |
| 可观测性 | middleware 内部不可见 | 每层独立日志 |
| 死代码 | `trim_messages_middleware` 定义但未接入 | 已删除 |

`create_agent()` 被替换为显式 StateGraph，给了后续定制（如加 hook、改路由策略、手动 compact 工具）更大空间。

## 5. 输出目录

Layer1 的持久化文件存放在 `.task_outputs/`，该目录已在 `.gitignore` 中，不会被提交到版本控制。

## 6. 扩展点

- **手动 compact**：后续可添加 `compact` 工具，模型或用户 `/compact` 命令触发强制压缩
- **阈值可配置化**：当前阈值硬编码在 `context_compactor.py` 顶部，后续可移到 `.env` 配置
- **CompactState**：可维护 `has_compacted` / `last_summary` 状态字段，供 Planner 感知是否已压缩
