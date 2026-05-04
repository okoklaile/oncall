"""RAG Agent 服务 — 显式 LangGraph 工作流

三层上下文压缩嵌入图循环：agent → tools → compact → agent

前面: app/api/chat.py 的 /chat 和 /chat_stream 接口
后面: retrieve_knowledge / get_current_time / retrieve_past_diagnoses / MCP 工具
"""

from typing import Annotated, Any, AsyncGenerator, Dict, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from loguru import logger
from typing_extensions import TypedDict
from langchain_qwq import ChatQwen

from app.config import config
from app.tools import get_current_time, retrieve_knowledge, retrieve_past_diagnoses
from app.agent.mcp_client import get_mcp_client_with_retry
from app.services.context_compactor import compact


# ============================================================
# 图内部状态
# ============================================================

class AgentInternalState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


# ============================================================
# RAG Agent 服务
# ============================================================

class RagAgentService:
    """RAG Agent — 显式 StateGraph，agent → tools → compact 循环"""

    def __init__(self, streaming: bool = True):
        self.model_name = config.rag_model
        self.summary_model_name = config.rag_summary_model or self.model_name
        self.streaming = streaming
        self.system_prompt = self._build_system_prompt()

        self.model = ChatQwen(
            model=self.model_name,
            api_key=config.dashscope_api_key,
            temperature=0.7,
            streaming=streaming,
        )
        self.summary_model = ChatQwen(
            model=self.summary_model_name,
            api_key=config.dashscope_api_key,
            temperature=0,
            streaming=False,
        )

        # 本地工具
        self.local_tools = [retrieve_knowledge, get_current_time, retrieve_past_diagnoses]
        self.mcp_tools: list = []

        # Checkpointer
        try:
            from langgraph.checkpoint.redis import AsyncRedisSaver
            self.checkpointer = AsyncRedisSaver(redis_url=config.redis_url)
            logger.info(f"AsyncRedis Checkpointer 初始化完成: {config.redis_url}")
        except Exception as e:
            logger.error(f"AsyncRedis Checkpointer 初始化失败，回退到内存模式: {e}")
            from langgraph.checkpoint.memory import MemorySaver
            self.checkpointer = MemorySaver()

        self.graph = None
        self._graph_ready = False

        logger.info(
            f"RAG Agent 服务初始化完成, model={self.model_name}, "
            f"summary_model={self.summary_model_name}, streaming={streaming}"
        )

    # ============================================================
    # 构建图
    # ============================================================

    async def _ensure_graph(self):
        if self._graph_ready:
            return

        # Checkpointer setup
        if hasattr(self.checkpointer, "setup"):
            try:
                await self.checkpointer.setup()
            except Exception as e:
                logger.error(f"Checkpointer setup 失败: {e}")

        # MCP 工具
        mcp_client = await get_mcp_client_with_retry()
        mcp_tools = await mcp_client.get_tools()
        logger.info(f"成功加载 {len(mcp_tools)} 个 MCP 工具")
        self.mcp_tools = mcp_tools

        all_tools = self.local_tools + self.mcp_tools
        tool_names = [t.name for t in all_tools if hasattr(t, "name")]
        logger.info(f"可用工具: {', '.join(tool_names)}")

        # 绑定工具到模型
        llm_with_tools = self.model.bind_tools(all_tools)

        # ---- 节点 ----

        async def agent_node(state: AgentInternalState) -> dict[str, Any]:
            response = await llm_with_tools.ainvoke(state["messages"])
            return {"messages": [response]}

        def should_continue(state: AgentInternalState) -> str:
            messages = state.get("messages", [])
            if not messages:
                return END
            last_msg = messages[-1]
            return "tools" if getattr(last_msg, "tool_calls", None) else END

        async def compact_node(state: AgentInternalState) -> dict[str, Any]:
            messages = list(state["messages"])
            compacted = await compact(messages, self.summary_model)
            return {"messages": compacted}

        # ---- 组装 ----

        workflow = StateGraph(AgentInternalState)
        workflow.add_node("agent", agent_node)
        workflow.add_node("tools", ToolNode(all_tools))
        workflow.add_node("compact", compact_node)

        workflow.set_entry_point("agent")
        workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
        workflow.add_edge("tools", "compact")
        workflow.add_edge("compact", "agent")

        self.graph = workflow.compile(checkpointer=self.checkpointer)
        self._graph_ready = True
        logger.info("RAG Agent 图构建完成 (agent → tools → compact → agent)")

    # ============================================================
    # System Prompt
    # ============================================================

    def _build_system_prompt(self) -> str:
        from textwrap import dedent
        return dedent("""
            你是一个专业的AI助手，能够使用多种工具来帮助用户解决问题。

            工作原则:
            1. 理解用户需求，选择合适的工具来完成任务
            2. 当需要获取实时信息或专业知识时，主动使用相关工具
            3. 基于工具返回的结果提供准确、专业的回答
            4. 如果工具无法提供足够信息，请诚实地告知用户

            回答要求:
            - 保持友好、专业的语气
            - 回答简洁明了，重点突出
            - 基于事实，不编造信息
            - 如有不确定的地方，明确说明

            请根据用户的问题，灵活使用可用工具，提供高质量的帮助。
        """).strip()

    # ============================================================
    # 非流式查询
    # ============================================================

    async def query(self, question: str, session_id: str) -> str:
        try:
            await self._ensure_graph()

            history = await self.get_session_history(session_id)
            messages = []
            if not history:
                messages.append(SystemMessage(content=self.system_prompt))
                logger.info(f"[会话 {session_id}] 新会话")
            else:
                logger.info(f"[会话 {session_id}] 恢复会话, 历史 {len(history)} 条")

            messages.append(HumanMessage(content=question))
            config_dict: RunnableConfig = {"configurable": {"thread_id": session_id}}

            result = await self.graph.ainvoke({"messages": messages}, config=config_dict)
            messages_result = result.get("messages", [])

            # 提取最终答案
            answer = ""
            for msg in reversed(messages_result):
                if not isinstance(msg, AIMessage):
                    continue
                content = getattr(msg, "content", None)
                if isinstance(content, str) and content.strip():
                    answer = content
                    break
                if isinstance(content, list):
                    text_parts = [
                        b.get("text", "")
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    if text_parts:
                        answer = "".join(text_parts)
                        break

            if not answer and messages_result:
                answer = str(messages_result[-1])

            logger.info(f"[会话 {session_id}] 查询完成, 回答长度={len(answer)}")
            return answer

        except Exception as e:
            logger.error(f"[会话 {session_id}] 查询失败: {e}")
            raise

    # ============================================================
    # 流式查询
    # ============================================================

    async def query_stream(
        self, question: str, session_id: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        try:
            await self._ensure_graph()

            history = await self.get_session_history(session_id)
            messages = []
            if not history:
                messages.append(SystemMessage(content=self.system_prompt))
                logger.info(f"[会话 {session_id}] 新会话(流式)")
            else:
                logger.info(f"[会话 {session_id}] 恢复会话(流式), 历史 {len(history)} 条")

            messages.append(HumanMessage(content=question))
            config_dict: RunnableConfig = {"configurable": {"thread_id": session_id}}

            async for msg, meta in self.graph.astream(
                {"messages": messages},
                config=config_dict,
                stream_mode="messages",
            ):
                node = meta.get("langgraph_node", "?") if isinstance(meta, dict) else "?"
                if isinstance(msg, (AIMessage,)) and hasattr(msg, "content_blocks"):
                    for block in getattr(msg, "content_blocks", []) or []:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                yield {"type": "content", "data": text, "node": node}

            yield {"type": "complete"}

        except Exception as e:
            logger.error(f"[会话 {session_id}] 流式查询失败: {e}")
            yield {"type": "error", "data": str(e)}
            raise

    # ============================================================
    # 会话历史
    # ============================================================

    async def get_session_history(self, session_id: str) -> list:
        try:
            await self._ensure_graph()
            state = await self.graph.aget_state({"configurable": {"thread_id": session_id}})
            if not state or not state.values or "messages" not in state.values:
                return []

            history: list[dict] = []
            for msg in state.values["messages"]:
                if isinstance(msg, SystemMessage):
                    continue
                role = "user" if isinstance(msg, HumanMessage) else "assistant"
                content = msg.content if hasattr(msg, "content") else str(msg)
                history.append({
                    "role": role,
                    "content": content,
                    "timestamp": msg.additional_kwargs.get("timestamp", ""),
                })
            return history
        except Exception as e:
            logger.error(f"获取会话历史失败: {session_id}, {e}")
            return []

    def clear_session(self, session_id: str) -> bool:
        try:
            import redis
            sync_redis = redis.from_url(config.redis_url, decode_responses=True)
            pattern = f"checkpoint:{session_id}:*"
            keys = sync_redis.keys(pattern)
            if keys:
                sync_redis.delete(*keys)
            logger.info(f"已清除会话: {session_id}, 删除 {len(keys)} 个键")
            return True
        except Exception as e:
            logger.error(f"清空会话失败: {session_id}, {e}")
            return False

    async def cleanup(self):
        logger.info("RAG Agent 资源已清理")


# 全局单例
rag_agent_service = RagAgentService(streaming=True)
