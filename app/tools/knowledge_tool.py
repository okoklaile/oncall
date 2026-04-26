"""知识检索工具 - 从向量数据库中检索相关信息"""

from typing import List, Tuple

from langchain_core.documents import Document
from langchain_core.tools import tool
from loguru import logger
from pymilvus import AnnSearchRequest, RRFRanker

from app.config import config
from app.core.milvus_client import milvus_manager
from app.services.vector_embedding_service import vector_embedding_service
from app.services.rerank_service import rerank_service


@tool(response_format="content_and_artifact")
def retrieve_knowledge(query: str) -> Tuple[str, List[Document]]:
    """从知识库中检索相关信息来回答问题
    
    使用三阶段检索流程:
    1. 粗排召回 (Recall): 并发向量召回 (Dense) 和 BM25 召回 (Sparse)，取前 50 个候选。
    2. RRF 融合 (Reciprocal Rank Fusion): 自动平衡两路召回结果。
    3. 精排 (Rerank): 使用 Cross-Encoder 模型对候选文档进行精准评分和重排，取前 Top-K。
    
    Args:
        query: 用户的问题或查询
        
    Returns:
        Tuple[str, List[Document]]: (格式化的上下文文本, 原始文档列表)
    """
    try:
        logger.info(f"知识检索工具被调用 (三阶段检索): query='{query}'")
        
        # 1. 获取 Milvus Collection
        collection = milvus_manager.get_collection()
        
        # 2. 准备向量召回请求 (Dense Search)
        query_vector = vector_embedding_service.embed_query(query)
        
        # 粗排阶段：候选池取大一些，为精排提供足够的素材
        recall_limit = 10 
        
        dense_search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}
        dense_req = AnnSearchRequest(
            data=[query_vector],
            anns_field="vector",
            param=dense_search_params,
            limit=recall_limit,
        )
        
        # 3. 准备 BM25 召回请求 (Sparse Search)
        sparse_search_params = {"metric_type": "BM25"}
        sparse_req = AnnSearchRequest(
            data=[query],
            anns_field="sparse_vector",
            param=sparse_search_params,
            limit=recall_limit,
        )
        
        # 4. 执行混合检索并使用 RRF 融合
        res = collection.hybrid_search(
            reqs=[dense_req, sparse_req],
            rerank=RRFRanker(),
            limit=recall_limit,
            output_fields=["content", "metadata"]
        )
        
        if not res or not res[0]:
            logger.warning("召回阶段未找到候选文档")
            return "没有找到相关信息。", []
            
        # 5. 提取召回候选文档
        candidate_docs = []
        for hit in res[0]:
            doc = Document(
                page_content=hit.entity.get("content"),
                metadata=hit.entity.get("metadata")
            )
            candidate_docs.append(doc)
            
        # 6. 精排阶段 (Rerank)
        # 将召回的 50 个候选文档交给精排模型，重新打分并取最终需要的 Top-K
        final_docs = rerank_service.rerank(
            query=query, 
            documents=candidate_docs, 
            top_n=config.rag_top_k
        )
        
        # 7. 格式化文档为上下文
        context = format_docs(final_docs)
        
        logger.info(f"检索完成: 召回 {len(candidate_docs)} 个候选 -> 精排保留 {len(final_docs)} 个文档")
        return context, final_docs
        
    except Exception as e:
        logger.error(f"知识检索工具调用失败: {e}")
        return f"检索知识时发生错误: {str(e)}", []


def format_docs(docs: List[Document]) -> str:
    """
    格式化文档列表为上下文文本
    
    Args:
        docs: 文档列表
        
    Returns:
        str: 格式化的上下文文本
    """
    formatted_parts = []
    
    for i, doc in enumerate(docs, 1):
        # 提取元数据
        metadata = doc.metadata
        source = metadata.get("_file_name", "未知来源")
        
        # 提取标题信息 (如果有)
        headers = []
        for key in ["h1", "h2", "h3"]:
            if key in metadata and metadata[key]:
                headers.append(metadata[key])
        
        header_str = " > ".join(headers) if headers else ""
        
        # 构建格式化文本
        formatted = f"【参考资料 {i}】"
        if header_str:
            formatted += f"\n标题: {header_str}"
        formatted += f"\n来源: {source}"
        formatted += f"\n内容:\n{doc.page_content}\n"
        
        formatted_parts.append(formatted)
    
    return "\n".join(formatted_parts)
