import os
import asyncio
from typing import List, Dict, Any
from langsmith import Client
from langsmith.evaluation import evaluate
from langchain_core.documents import Document
from loguru import logger

# 设置环境变量以确保可以使用相关模块
os.environ["PYTHONPATH"] = os.getcwd()

# 导入要测试的工具
# 注意：这需要确保环境已经安装了 app 目录下的依赖
from app.config import config
from app.core.llm_factory import llm_factory

# 手动同步配置到环境变量，因为 LangSmith SDK 会从环境变量读取
os.environ["LANGCHAIN_TRACING_V2"] = str(config.langchain_tracing_v2).lower()
os.environ["LANGCHAIN_ENDPOINT"] = config.langchain_endpoint
os.environ["LANGCHAIN_API_KEY"] = config.langchain_api_key
os.environ["LANGCHAIN_PROJECT"] = config.langchain_project

from app.tools.knowledge_tool import retrieve_knowledge
from app.core.milvus_client import milvus_manager

async def generate_examples_from_milvus(limit: int = 5) -> List[Dict[str, Any]]:
    """从 Milvus 数据库中提取真实文档并生成测试用例"""
    logger.info(f"正在从 Milvus 提取 {limit} 条真实文档以生成测试用例...")
    
    collection = milvus_manager.get_collection()
    # 随机获取一些文档
    res = collection.query(expr="", limit=limit, output_fields=["content"])
    
    if not res:
        logger.warning("Milvus 数据库中没有文档，无法生成真实测试用例。")
        return []

    llm = llm_factory.create_chat_model(
        model=config.rag_model,
        temperature=0.1,
        streaming=False
    )
    
    examples = []
    for doc in res:
        content = doc.get("content", "")
        if not content: continue
        
        # 使用 LLM 根据内容生成问题
        prompt = f"""你是一个运维专家。请根据以下文档内容，生成一个用户可能会问的、能够通过该文档回答的简短问题。
并提取出回答该问题所需的 3-5 个核心关键词。

文档内容:
{content[:500]}...

请直接返回以下 JSON 格式，不要有其他解释:
{{
  "question": "生成的问题",
  "expected_keywords": ["关键词1", "关键词2", "关键词3"]
}}
"""
        try:
            response = await llm.ainvoke(prompt)
            # 简单解析 JSON
            import json
            import re
            
            # 提取 JSON 块
            match = re.search(r'\{.*\}', response.content, re.DOTALL)
            if match:
                data = json.loads(match.group())
                examples.append({
                    "inputs": {"query": data["question"]},
                    "outputs": {"expected_keywords": data["expected_keywords"]}
                })
                logger.info(f"生成用例: {data['question']}")
        except Exception as e:
            logger.error(f"生成用例失败: {e}")
            
    return examples

async def create_dataset(client: Client, dataset_name: str, use_real_data: bool = True):
    """创建或获取评测数据集"""
    if client.has_dataset(dataset_name=dataset_name):
        logger.info(f"数据集 '{dataset_name}' 已存在。")
        return client.read_dataset(dataset_name=dataset_name)
    
    logger.info(f"正在创建数据集 '{dataset_name}'...")
    dataset = client.create_dataset(dataset_name=dataset_name, description="AIOps RAG 真实数据检索评测数据集")
    
    if use_real_data:
        examples = await generate_examples_from_milvus(limit=10)
    else:
        # 兜底的硬编码用例
        examples = [
            {
                "inputs": {"query": "如何解决 Redis 内存碎片率过高的问题？"},
                "outputs": {"expected_keywords": ["activedefrag", "memory purge", "碎片率"]}
            }
        ]
    
    for ex in examples:
        client.create_example(
            inputs=ex["inputs"],
            outputs=ex["outputs"],
            dataset_id=dataset.id
        )
    return dataset

def retrieval_target(inputs: dict) -> dict:
    """评估目标函数：封装 retrieve_knowledge 工具"""
    query = inputs.get("query")
    # 直接调用底层的函数以获取 (context, docs) 元组
    # retrieve_knowledge 是一个 LangChain Tool 对象，其原始函数在 .func 属性中
    context, docs = retrieve_knowledge.func(query)
    
    # 返回提取出的文档内容列表，供评估器使用
    return {
        "retrieved_contents": [doc.page_content for doc in docs],
        "doc_count": len(docs)
    }

def evaluate_hit_rate(run: Any, example: Any) -> dict:
    """评估器：命中率 (Hit Rate)
    判断检索到的文档中是否包含预期关键词中的至少一个
    """
    retrieved_contents = run.outputs.get("retrieved_contents", [])
    expected_keywords = example.outputs.get("expected_keywords", [])
    
    if not retrieved_contents:
        return {"key": "hit_rate", "score": 0, "comment": "未检索到任何文档"}
    
    # 合并所有检索到的内容进行搜索
    all_content = " ".join(retrieved_contents).lower()
    
    hits = 0
    matched_keywords = []
    for kw in expected_keywords:
        if kw.lower() in all_content:
            hits += 1
            matched_keywords.append(kw)
    
    score = 1 if hits > 0 else 0
    return {
        "key": "hit_rate",
        "score": score,
        "comment": f"匹配到的关键词: {matched_keywords}" if hits > 0 else "未匹配到任何预期关键词"
    }

def evaluate_mrr(run: Any, example: Any) -> dict:
    """评估器：平均倒数排名 (MRR)
    计算第一个包含预期关键词的文档所在的排名倒数
    """
    retrieved_contents = run.outputs.get("retrieved_contents", [])
    expected_keywords = example.outputs.get("expected_keywords", [])
    
    if not retrieved_contents:
        return {"key": "mrr", "score": 0}
    
    for i, content in enumerate(retrieved_contents, 1):
        content_lower = content.lower()
        if any(kw.lower() in content_lower for kw in expected_keywords):
            return {"key": "mrr", "score": 1.0 / i}
            
    return {"key": "mrr", "score": 0}

async def main():
    client = Client()
    dataset_name = "AIOps_Retrieval_RealData_v2"
    
    # 0. 初始化 Milvus 连接
    logger.info("正在连接 Milvus...")
    milvus_manager.connect()
    
    # 1. 准备数据集
    await create_dataset(client, dataset_name)
    
    # 2. 运行评估
    logger.info("开始执行评测...")
    results = evaluate(
        retrieval_target,
        data=dataset_name,
        evaluators=[evaluate_hit_rate, evaluate_mrr],
        experiment_prefix="hybrid-search-eval",
        max_concurrency=1  # 避免并发过高导致 API 限制
    )
    
    logger.info("评测执行完成！请前往 LangSmith 控制台查看详细报告。")

if __name__ == "__main__":
    asyncio.run(main())
