"""文件读取工具 — 读取持久化到磁盘的工具输出"""

from pathlib import Path

from langchain_core.tools import tool
from loguru import logger

MAX_CHARS = 8000  # 单次读取上限，控制在 Layer1 落盘阈值以下，避免循环落盘


@tool
def read_task_output(filepath: str, offset: int = 0, limit: int = MAX_CHARS) -> str:
    """读取之前持久化到磁盘的工具输出内容。

    当上下文中出现 <persisted-output> 标记时，说明某次工具调用的完整输出被写入了磁盘。
    使用此工具可以读取该文件的完整内容。如果文件较大，可以通过 offset 参数分段读取。

    Args:
        filepath: 文件路径，即 <persisted-output> 标记中 file: 后面的路径
        offset: 从第几个字符开始读（默认 0），用于分段读取大文件
        limit: 最多读取多少字符（默认 8000）

    Returns:
        文件内容，含已读范围和总大小信息
    """
    path = Path(filepath)
    if not path.exists():
        return f"文件不存在: {filepath}"

    try:
        text = path.read_text(encoding="utf-8")
        total = len(text)
        chunk = text[offset:offset + limit]
        read_end = min(offset + len(chunk), total)

        header = f"文件: {filepath}\n范围: {offset}-{read_end} / {total} 字符\n"
        if read_end < total:
            header += f"(还有 {total - read_end} 字符未读，可调整 offset={read_end} 继续)\n"
        header += "-" * 40 + "\n"

        logger.info(f"read_task_output: {filepath} [{offset}:{read_end}/{total}]")
        return header + chunk

    except Exception as e:
        return f"读取失败: {e}"
