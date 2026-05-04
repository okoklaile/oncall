"""三层上下文压缩服务

Layer1 - 大工具输出落盘: 超大输出→磁盘, 上下文只留预览+路径
Layer2 - 微压缩: 保留最近3个工具结果, 更早的替换为占位符
Layer3 - 摘要压缩: 整段历史→LLM摘要 (仅在前两层仍超限时触发)

嵌入位置: agent_graph 中 tools_node 之后、agent_node 之前
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from loguru import logger

# ============================================================
# 阈值配置
# ============================================================

PERSIST_THRESHOLD = 8000        # 字符, 工具输出超过此值触发落盘 (~2000 tokens)
MICRO_KEEP_LAST = 3             # 微压缩保留最近 N 个工具结果原文
CONTEXT_CHAR_LIMIT = 48000      # 字符, 整体上下文超过此值触发摘要 (~12000 tokens, 按 1token≈4char)


# ============================================================
# 输出目录
# ============================================================

OUTPUT_DIR = Path(".task_outputs")


def _ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 估算 token 数 (粗略: 1 token ≈ 4 字符)
# ============================================================

def _estimate_chars(messages: Sequence[BaseMessage]) -> int:
    total = 0
    for m in messages:
        content = getattr(m, "content", "")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += len(str(block))
    return total


# ============================================================
# Layer 1: 大工具输出落盘
# ============================================================

def persist_large_outputs(messages: list[BaseMessage]) -> list[BaseMessage]:
    """工具输出超过阈值时写入磁盘，上下文只留预览和文件路径。"""
    _ensure_output_dir()

    for i, msg in enumerate(messages):
        if not isinstance(msg, ToolMessage):
            continue
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        if len(content) <= PERSIST_THRESHOLD:
            continue

        tool_call_id = getattr(msg, "tool_call_id", f"unknown-{i}")
        name = getattr(msg, "name", "unknown")
        file_path = OUTPUT_DIR / f"{tool_call_id}.txt"

        try:
            file_path.write_text(content, encoding="utf-8")
        except Exception:
            logger.exception(f"Layer1: 落盘失败 tool_call_id={tool_call_id}")
            continue

        preview = content[:2000]
        messages[i].content = (
            f"<persisted-output>\n"
            f"tool: {name}\n"
            f"file: {file_path}\n"
            f"preview ({len(preview)}/{len(content)} chars):\n"
            f"{preview}\n"
            f"</persisted-output>"
        )
        logger.info(f"Layer1: persisted output, tool={name}, size={len(content)} -> preview={len(preview)}")

    return messages


# ============================================================
# Layer 2: 微压缩 — 旧工具结果替换为占位符
# ============================================================

def micro_compact(messages: list[BaseMessage]) -> list[BaseMessage]:
    """保留最近 MICRO_KEEP_LAST 条工具结果原文，更早的替换为占位符。"""
    tool_indices = [
        (i, m) for i, m in enumerate(messages)
        if isinstance(m, ToolMessage)
    ]

    if len(tool_indices) <= MICRO_KEEP_LAST:
        return messages

    compacted = 0
    for idx, msg in tool_indices[:-MICRO_KEEP_LAST]:
        name = getattr(msg, "name", "unknown")
        messages[idx].content = f"[Earlier tool result: {name} — omitted for brevity]"
        compacted += 1

    if compacted:
        logger.info(f"Layer2: micro compacted {compacted} tool results, kept last {MICRO_KEEP_LAST}")

    return messages


# ============================================================
# Layer 3: 摘要压缩
# ============================================================

SUMMARY_SYSTEM_PROMPT = """你是对话压缩器。将以下对话历史压缩为简洁摘要。

必须保留的关键信息：
1. 用户任务目标
2. 已完成的步骤和结论
3. 涉及的工具名称（如 search_log、retrieve_knowledge 等）
4. 重要的文件路径或数据源
5. 未解决的关键问题

格式：用"## 对话摘要"开头，分段组织，不超过500字。"""


async def summary_compact(
    messages: list[BaseMessage],
    summary_model,
) -> list[BaseMessage]:
    """将全部消息历史压缩为一段摘要。"""
    # 拼接对话文本
    parts: list[str] = []
    for m in messages:
        content = getattr(m, "content", "")
        if isinstance(content, list):
            content = " ".join(
                b.get("text", "") for b in content if isinstance(b, dict)
            )

        if isinstance(m, SystemMessage):
            parts.append(f"[System]: {str(content)[:200]}")
        elif isinstance(m, HumanMessage):
            parts.append(f"[User]: {str(content)}")
        elif isinstance(m, AIMessage):
            parts.append(f"[Assistant]: {str(content)[:500]}")
        elif isinstance(m, ToolMessage):
            name = getattr(m, "name", "tool")
            parts.append(f"[Tool {name}]: {str(content)[:300]}")

    conv_text = "\n".join(parts)
    logger.info(f"Layer3: summarizing {len(messages)} messages, {len(conv_text)} chars")

    try:
        response = await summary_model.ainvoke([
            SystemMessage(content=SUMMARY_SYSTEM_PROMPT),
            HumanMessage(content=f"请压缩以下对话历史：\n\n{conv_text}"),
        ])
    except Exception:
        logger.exception("Layer3: summary model call failed")
        return messages

    summary = response.content if hasattr(response, "content") else str(response)

    return [
        SystemMessage(content="以下为压缩后的对话历史，原始细节已省略，关键信息保留如下："),
        HumanMessage(content=f"[Compacted]\n\n{summary}"),
    ]


# ============================================================
# 统一入口
# ============================================================

@dataclass
class CompactResult:
    compacted: bool = False
    layers: list[int] = field(default_factory=list)
    before_chars: int = 0
    after_chars: int = 0


async def compact(
    messages: list[BaseMessage],
    summary_model,
    *,
    force_summary: bool = False,
) -> list[BaseMessage]:
    """对消息列表执行三层压缩，返回压缩后的消息。

    Layer1 和 Layer2 始终执行（纯文本处理，无 LLM 开销）。
    Layer3 仅在 force_summary=True 或上下文仍超 CONTEXT_CHAR_LIMIT 时触发。
    """
    before = _estimate_chars(messages)
    result = CompactResult(before_chars=before)

    # Layer 1
    messages = persist_large_outputs(messages)
    result.layers.append(1)

    # Layer 2
    messages = micro_compact(messages)
    result.layers.append(2)

    # Layer 3 — 按需
    after_l2 = _estimate_chars(messages)
    if force_summary or after_l2 > CONTEXT_CHAR_LIMIT:
        messages = await summary_compact(messages, summary_model)
        result.layers.append(3)
        logger.info("Layer3: summary compact applied")

    result.after_chars = _estimate_chars(messages)
    result.compacted = result.after_chars < result.before_chars

    if result.compacted:
        logger.info(
            f"Compact: {result.before_chars} -> {result.after_chars} chars "
            f"(-{(1 - result.after_chars / max(result.before_chars, 1)) * 100:.0f}%), "
            f"layers={result.layers}"
        )
    else:
        logger.info(
            f"Compact: no action needed, {result.after_chars} chars, "
            f"layers={result.layers}"
        )

    return messages
