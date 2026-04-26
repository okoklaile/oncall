# Milvus 2.5+ 原生 BM25 混合检索与三阶段精排实现指南

本文档记录了在 SuperBizAgent 项目中实现 **Recall (粗排) -> Rerank (精排)** 三阶段检索架构的过程。

## 1. 技术架构
为了实现极致的检索精度，我们采用了工业界标准的检索流程：
1.  **Recall (粗排召回)**：利用 Milvus 并发执行向量检索（语义）和 BM25 检索（关键词），从海量数据中取 Top 50。
2.  **RRF (融合)**：使用 Reciprocal Rank Fusion 自动平衡两路召回结果。
3.  **Rerank (精排重排)**：利用 Cross-Encoder 模型（DashScope gte-rerank）对候选文档进行深度相关性打分，保留最终的 Top-K。

## 2. 核心实现步骤

### 2.1 依赖与配置
- **SDK**: `pymilvus>=2.5.0`, `dashscope`
- **模型**: `gte-rerank` (阿里云精排模型)

### 2.2 Milvus Schema 改造 (粗排基础)
在 Collection 中增加稀疏向量字段，并配置 BM25 函数。
- **Content 字段**：开启 `enable_analyzer=True`。
- **Sparse Vector 字段**：类型为 `SPARSE_FLOAT_VECTOR`。
- **Function**：定义 BM25 Function 自动从 `content` 生成 `sparse_vector`。

### 2.3 精排服务封装 (Rerank Service)
在 `app/services/rerank_service.py` 中封装了对 DashScope Reranker 的调用。精排模型能看到 Query 和 Doc 的完整文本，进行深度语义交叉比对，弥补粗排阶段只看特征向量的不足。

### 2.4 三阶段检索流程逻辑
在 `knowledge_tool.py` 中实现了完整的编排逻辑：

```python
# 1. 粗排阶段 (取 50 个候选)
res = collection.hybrid_search(
    reqs=[dense_req, sparse_req],
    rerank=RRFRanker(),
    limit=50, 
    output_fields=["content", "metadata"]
)

# 2. 精排阶段 (重排并截断为最终 Top-K)
final_docs = rerank_service.rerank(
    query=query, 
    documents=candidate_docs, 
    top_n=config.rag_top_k
)
```

## 3. 为什么选择三阶段架构？
- **Recall (向量)**：擅长“意思相近”。
- **Recall (BM25)**：擅长“字面匹配”。
- **Rerank (精排)**：擅长“逻辑判断”，能剔除那些特征相似但逻辑无关的噪声。

## 4. 迁移与注意事项
- **候选池大小**：精排候选池（Recall Limit）通常设为 50-100。
- **降级机制**：精排服务异常时，系统会自动降级返回粗排结果，确保服务高可用。
