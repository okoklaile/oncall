"""长期记忆检索工具 — 搜索历史诊断经验"""

from langchain_core.tools import tool
from loguru import logger

from app.services.long_term_memory import search_aiops


@tool
def retrieve_past_diagnoses(query: str) -> str:
    """搜索历史 AIOps 诊断报告，获取过去成功处理过的类似问题经验。

    当需要排查告警、分析故障、制定诊断计划时，先用此工具查历史经验。
    返回的是已确认修复成功的案例，包含当时的诊断方案和处理结果。

    Args:
        query: 搜索关键词，如服务名、告警类型、问题描述等

    Returns:
        匹配的历史诊断记录，含完整报告内容
    """
    logger.info(f"长期记忆检索: query='{query}'")

    records = search_aiops(keyword=query, confirmed_only=True, limit=3)

    if not records:
        return f"未找到与 '{query}' 相关的历史诊断记录。"

    lines = [f"找到 {len(records)} 条相关历史诊断经验：\n"]
    for i, r in enumerate(records, 1):
        lines.append(f"---")
        lines.append(f"### 历史案例 {i}")
        lines.append(f"- 诊断ID: {r['id']}")
        lines.append(f"- 时间: {r['created_at']}")
        lines.append(f"- 任务描述: {r['input_text'][:200]}")
        lines.append(f"\n#### 诊断报告\n{r['response']}")

    return "\n".join(lines)
