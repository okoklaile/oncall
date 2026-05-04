"""长期记忆服务 — SQLite 持久化存储。

与 Milvus 向量库职责分离：
- SQLite: AIOps 诊断报告 + 对话沉淀，结构化精确查询
- Milvus: 人工上传的知识文档，语义检索
"""

import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from loguru import logger

TZ = timezone(timedelta(hours=8))
DB_DIR = Path("data")
DB_PATH = DB_DIR / "long_term_memory.db"


def _now() -> str:
    return datetime.now(TZ).isoformat()


def _ensure_db() -> None:
    """确保数据库文件和表已创建。"""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS aiops_memory (
                id              TEXT PRIMARY KEY,
                input_text      TEXT DEFAULT '',
                response        TEXT NOT NULL,
                confirmed       INTEGER NOT NULL DEFAULT 1,
                source_type     TEXT NOT NULL DEFAULT 'aiops',
                created_at      TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_memory (
                id              TEXT PRIMARY KEY,
                content         TEXT NOT NULL,
                topic           TEXT DEFAULT '',
                session_id      TEXT DEFAULT '',
                source_type     TEXT NOT NULL DEFAULT 'chat',
                created_at      TEXT NOT NULL
            )
        """)
        conn.commit()


def _conn() -> sqlite3.Connection:
    _ensure_db()
    return sqlite3.connect(str(DB_PATH))


# ============================================================
# AIOps 记忆
# ============================================================

def store_aiops(response: str, input_text: str = "", confirmed: bool = True) -> Optional[str]:
    """存入一条 AIOps 诊断报告。

    Args:
        response: 诊断报告全文（Markdown）
        input_text: 原始任务描述
        confirmed: 运维确认修复成功

    Returns:
        诊断 ID，失败返回 None
    """
    if not response or not response.strip():
        logger.info("AIOps 记忆: 报告为空，跳过")
        return None

    diagnosis_id = f"aiops-{datetime.now(TZ).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    try:
        with _conn() as conn:
            conn.execute(
                """INSERT INTO aiops_memory (id, input_text, response, confirmed, source_type, created_at)
                   VALUES (?, ?, ?, ?, 'aiops', ?)""",
                (diagnosis_id, input_text[:500], response, int(confirmed), _now()),
            )
            conn.commit()

        logger.info(
            f"AIOps 记忆: 入库完成 id={diagnosis_id}, confirmed={confirmed}, "
            f"报告长度={len(response)}"
        )
        return diagnosis_id

    except Exception:
        logger.exception(f"AIOps 记忆: 入库失败 id={diagnosis_id}")
        return None


def search_aiops(
    keyword: str = "",
    confirmed_only: bool = True,
    limit: int = 5,
) -> list[dict]:
    """搜索历史 AIOps 诊断记录。

    Args:
        keyword: 搜索关键词（模糊匹配 input_text 和 response）
        confirmed_only: 仅返回确认修复成功的记录
        limit: 最大返回数

    Returns:
        匹配的诊断记录列表
    """
    try:
        with _conn() as conn:
            conn.row_factory = sqlite3.Row
            wheres = []
            params: list = []

            if confirmed_only:
                wheres.append("confirmed = 1")

            if keyword:
                wheres.append("(input_text LIKE ? OR response LIKE ?)")
                kw = f"%{keyword}%"
                params.extend([kw, kw])

            where_clause = " AND ".join(wheres) if wheres else "1=1"
            sql = (
                f"SELECT id, input_text, response, confirmed, created_at "
                f"FROM aiops_memory "
                f"WHERE {where_clause} "
                f"ORDER BY created_at DESC "
                f"LIMIT ?"
            )
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    except Exception:
        logger.exception("AIOps 记忆: 搜索失败")
        return []


# ============================================================
# Chat 记忆
# ============================================================

def store_chat(content: str, topic: str = "", session_id: str = "") -> Optional[str]:
    """存入一条对话沉淀记忆。

    Args:
        content: 记忆内容
        topic: 主题/标签（逗号分隔）
        session_id: 来源会话 ID

    Returns:
        记忆 ID，失败返回 None
    """
    if not content or not content.strip():
        return None

    mem_id = f"chat-{datetime.now(TZ).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    try:
        with _conn() as conn:
            conn.execute(
                """INSERT INTO chat_memory (id, content, topic, session_id, source_type, created_at)
                   VALUES (?, ?, ?, ?, 'chat', ?)""",
                (mem_id, content, topic, session_id, _now()),
            )
            conn.commit()

        logger.info(f"Chat 记忆: 入库完成 id={mem_id}, topic={topic}")
        return mem_id

    except Exception:
        logger.exception(f"Chat 记忆: 入库失败 id={mem_id}")
        return None


def search_chat(keyword: str = "", limit: int = 5) -> list[dict]:
    """搜索对话记忆。

    Args:
        keyword: 搜索关键词
        limit: 最大返回数

    Returns:
        匹配的记忆列表
    """
    try:
        with _conn() as conn:
            conn.row_factory = sqlite3.Row
            if keyword:
                rows = conn.execute(
                    """SELECT id, content, topic, session_id, created_at
                       FROM chat_memory
                       WHERE content LIKE ? OR topic LIKE ?
                       ORDER BY created_at DESC
                       LIMIT ?""",
                    (f"%{keyword}%", f"%{keyword}%", limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT id, content, topic, session_id, created_at
                       FROM chat_memory
                       ORDER BY created_at DESC
                       LIMIT ?""",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    except Exception:
        logger.exception("Chat 记忆: 搜索失败")
        return []
