"""文件读取工具 — 读取持久化到磁盘的工具输出，支持关键词过滤和指定行数"""

from pathlib import Path

from langchain_core.tools import tool
from loguru import logger

MAX_LINES = 200  # 单次读取行数上限


@tool
def read_task_output(
    filepath: str,
    grep: str = "",
    offset: int = 0,
    limit: int = MAX_LINES,
) -> str:
    """读取之前持久化到磁盘的工具输出内容。

    当上下文中出现 <persisted-output> 标记时，说明某次工具调用的完整输出被写入了磁盘。
    使用此工具可以读取该文件的完整内容，支持两种模式：

    1. 关键词过滤: 指定 grep 参数，只返回包含该关键词的行
    2. 指定行数: offset/limit 按行读取，默认读前 200 行

    两种模式可以组合使用——先 grep 过滤，再 offset/limit 取结果中的指定行。

    Args:
        filepath: 文件路径，<persisted-output> 标记中 file: 后面的路径
        grep: 关键词过滤，只返回包含该关键词的行（可选）
        offset: 从第几行开始读（默认 0），在 grep 过滤后的结果中取
        limit: 最多读多少行（默认 200）

    Returns:
        文件内容，含命中行数和范围信息
    """
    path = Path(filepath)
    if not path.exists():
        return f"文件不存在: {filepath}"

    try:
        text = path.read_text(encoding="utf-8")
        all_lines = text.split("\n")

        # grep 过滤
        if grep:
            matched = [l for l in all_lines if grep.lower() in l.lower()]
            if not matched:
                return f"文件: {filepath}\n共 {len(all_lines)} 行\n关键词 \"{grep}\" 未匹配到任何行"
        else:
            matched = all_lines

        total_matched = len(matched)

        # 按行切片
        chunk = matched[offset:offset + limit]
        read_start = offset
        read_end = offset + len(chunk)

        header = f"文件: {filepath}\n"
        if grep:
            header += f"关键词: \"{grep}\" → 匹配 {total_matched} 行\n"
        else:
            header += f"共 {total_matched} 行\n"
        header += f"范围: {read_start}-{read_end} / {total_matched} 行\n"
        if read_end < total_matched:
            header += f"(还有 {total_matched - read_end} 行未读，可调整 offset={read_end} 继续)\n"
        header += "-" * 40 + "\n"

        logger.info(f"read_task_output: {filepath} grep={grep!r} offset={offset} total={total_matched}")
        return header + "\n".join(chunk)

    except Exception as e:
        return f"读取失败: {e}"
