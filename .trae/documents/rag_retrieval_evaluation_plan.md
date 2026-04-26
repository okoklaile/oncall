# RAG 检索质量评测方案 (LangSmith)

本方案旨在参考 LangSmith 官方教程，针对 `retrieve_knowledge` 工具的**检索准确率**进行专项评测，而不涉及最终回答的生成质量。

## 1. 评测目标
- **验证混合检索效果**：评估 Dense (向量) + Sparse (BM25) 召回的组合是否比单一手段更优。
- **验证精排 (Rerank) 收益**：评估 `gte-rerank` 是否成功将最相关的文档排到了 Top-1/Top-3。
- **量化检索指标**：主要关注 **Hit Rate (命中率)** 和 **MRR (平均倒数排名)**。

## 2. 评测环境准备
- **环境变量**：确保 `.env` 中的 `LANGCHAIN_TRACING_V2=true` 和 `LANGCHAIN_API_KEY` 已正确配置。
- **依赖安装**：需要安装 `langsmith` SDK（如果尚未安装）。

## 3. 实施步骤

### 步骤 A：构建评测数据集 (LangSmith Dataset)
我们将编写一个脚本，在 LangSmith 平台上创建一个名为 `AIOps Retrieval Dataset` 的数据集。
- **输入 (Input)**：典型的运维查询问题（例如：“如何解决 Redis 内存碎片率过高的问题？”）。
- **预期输出 (Reference)**：该问题对应的核心关键词、文档标签或预期的文档 ID 片段。

### 步骤 B：编写评测逻辑
新建 `tests/eval/retrieval_eval.py` 脚本，核心逻辑包括：
1.  **定义评估目标函数**：封装 `retrieve_knowledge`，使其接收 query 并返回检索到的文档列表。
2.  **定义自定义评估器 (Evaluators)**：
    - **`document_relevance`**：利用 LLM 或关键词匹配判断检索出的前 N 个分片是否包含解决问题所需的关键信息。
    - **`reciprocal_rank`**：计算标准答案所在的排名。

### 步骤 C：执行评测循环
使用 LangSmith 的 `evaluate` 函数运行评测：
- 遍历数据集中的每一个问题。
- 调用 `retrieve_knowledge` 获取实时检索结果。
- 触发评估器进行打分。
- 结果自动上传至 LangSmith Dashboard。

## 4. 预期产出
- **LangSmith 评测看板**：直观展示每一个测试用例的检索链路追踪。
- **检索准确率报告**：
    - **Hit Rate@3**：前 3 个结果中包含正确答案的比例。
    - **Latency**：平均检索耗时（包含召回、融合、精排全过程）。

## 5. 验证与后续优化
- **坏例分析 (Bad Case Analysis)**：在 LangSmith 中找出检索失败的案例。
- **调优策略**：根据评测结果，调整 `recall_limit` (目前为 10) 或分块大小 (`chunk_max_size`)，并再次运行评测进行对比。

---
**确认后，我将开始创建评测脚本并准备示例数据集。**
