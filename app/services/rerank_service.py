"""精排服务 - 封装 DashScope Reranker 接口

作用:
- 接收召回阶段的候选文档，使用 Cross-Encoder 模型进行精准评分和重排。

后面是谁:
- 上游是 knowledge_tool.py 的召回阶段。
- 依赖 dashscope SDK 调用阿里云精排模型 (gte-rerank)。
"""

from typing import List
import dashscope
from langchain_core.documents import Document
from loguru import logger
from http import HTTPStatus

from app.config import config


class RerankService:
    """精排服务"""

    def __init__(self):
        """初始化精排服务"""
        self.api_key = config.dashscope_api_key
        self.model = config.dashscope_rerank_model
        logger.info(f"精排服务初始化完成: model={self.model}")

    def rerank(self, query: str, documents: List[Document], top_n: int = 5) -> List[Document]:
        """
        对文档进行精排

        Args:
            query: 查询文本
            documents: 候选文档列表
            top_n: 返回前 N 个文档

        Returns:
            List[Document]: 重新排序后的前 N 个文档
        """
        if not documents:
            return []

        try:
            # 1. 提取文档内容文本
            doc_contents = [doc.page_content for doc in documents]

            # 2. 调用 DashScope Reranker API
            logger.info(f"开始精排: query='{query}', 候选文档数={len(documents)}")
            
            response = dashscope.TextReRank.call(
                model=self.model,
                query=query,
                documents=doc_contents,
                top_n=top_n,
                return_documents=False, # 我们只需要索引和分数，内容我们已经有了
                api_key=self.api_key
            )

            if response.status_code != HTTPStatus.OK:
                logger.error(f"精排 API 调用失败: code={response.code}, message={response.message}")
                # 如果精排失败，降级返回原始的前 top_n 个文档
                return documents[:top_n]

            # 3. 根据精排结果重新组织文档
            reranked_docs = []
            for result in response.output.results:
                index = result.index
                score = result.relevance_score
                
                # 获取原始文档并更新元数据（可选，记录精排分数）
                doc = documents[index]
                doc.metadata["rerank_score"] = score
                reranked_docs.append(doc)

            logger.info(f"精排完成: 返回 {len(reranked_docs)} 个文档")
            return reranked_docs

        except Exception as e:
            logger.error(f"精排过程发生异常: {e}")
            # 异常时降级返回原始结果
            return documents[:top_n]


# 全局单例
rerank_service = RerankService()
