"""AIOps 长期记忆存储

将已确认修复成功的诊断报告写入 SQLite，标记 source_type="aiops"，
供后续 Planner 检索历史经验时参考（通过 search_aiops）。
"""

from loguru import logger

from app.services.long_term_memory import store_aiops


async def store_aiops_memory(response: str, input_text: str = "") -> bool:
    """将已确认修复成功的诊断报告写入 SQLite 长期记忆。

    Args:
        response: 诊断报告正文（Markdown）
        input_text: 原始任务描述

    Returns:
        bool: 是否入库成功
    """
    if not response or not response.strip():
        logger.info("AIOps 记忆存储: 报告为空，跳过")
        return False

    diagnosis_id = store_aiops(response=response, input_text=input_text, confirmed=True)
    return diagnosis_id is not None
