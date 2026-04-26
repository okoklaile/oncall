"""RAG Agent 服务 - 基于 LangGraph 的智能代理

作用:
- 编排对话主流程，驱动大模型与工具协同完成 RAG 问答。

前面是谁:
- 上游是 app/api/chat.py 的 /chat 和 /chat_stream 接口。

后面是谁:
- 下游会调用 retrieve_knowledge/get_current_time/MCP 工具，并由 ChatQwen 生成最终回答。

使用 langchain_qwq 的 ChatQwen 原生集成，
支持真正的流式输出和更好的模型适配。
"""

from typing import Annotated, Any, AsyncGenerator, Dict, Sequence

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)
from redis.asyncio import Redis as AsyncRedis
from langgraph.checkpoint.redis import AsyncRedisSaver
from langgraph.graph.message import REMOVE_ALL_MESSAGES, add_messages
from loguru import logger
from typing_extensions import TypedDict
from langchain_qwq import ChatQwen

from app.config import config
from app.tools import get_current_time, retrieve_knowledge
from app.agent.mcp_client import get_mcp_client_with_retry

# 阿里千问大模型和langchain集成参考： https://docs.langchain.com/oss/python/integrations/chat/qwen
# 注意：需要配置环境变量 DASHSCOPE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1 否则默认访问的是新加坡站点
# 同时也需要配置环境变量 DASHSCOPE_API_KEY=your_api_key


class AgentState(TypedDict):
    """Agent 状态"""
    messages: Annotated[Sequence[BaseMessage], add_messages]


def trim_messages_middleware(state: AgentState) -> dict[str, Any] | None:
    """
    修剪消息历史，只保留最近的几条消息以适应上下文窗口

    策略：
    - 保留第一条系统消息（System Message）
    - 保留最近的 6 条消息（3 轮对话）
    - 当消息少于等于 7 条时，不做修剪

    Args:
        state: Agent 状态

    Returns:
        包含修剪后消息的字典，如果无需修剪则返回 None
    """
    messages = state["messages"]

    # 如果消息数量较少，无需修剪
    if len(messages) <= 7:
        return None

    # 提取第一条系统消息
    first_msg = messages[0]

    # 保留最近的 6 条消息（确保包含完整的对话轮次）
    recent_messages = messages[-6:] if len(messages) % 2 == 0 else messages[-7:]

    # 构建新的消息列表
    new_messages = [first_msg] + list(recent_messages)

    logger.debug(f"修剪消息历史: {len(messages)} -> {len(new_messages)} 条")

    return {
        "messages": [
            RemoveMessage(id=REMOVE_ALL_MESSAGES),
            *new_messages
        ]
    }


class RagAgentService:
    """RAG Agent 服务 - 使用 LangGraph + ChatQwen 原生集成"""

    def __init__(self, streaming: bool = True):
        """初始化 RAG Agent 服务

        Args:
            streaming: 是否启用流式输出，默认为 True
        """
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

        # 定义基础工具
        self.tools = [retrieve_knowledge, get_current_time]

        # MCP 客户端（延迟初始化，使用全局管理）
        self.mcp_tools: list = []

        # 创建 Redis 检查点（用于会话持久化管理）
        try:
            # 根据源码 (aio.py)，AsyncRedisSaver 接收的是 redis_url 或 redis_client
            # 我们直接传递 redis_url 字符串，让库内部去管理异步连接
            self.checkpointer = AsyncRedisSaver(redis_url=config.redis_url)
            logger.info(f"AsyncRedis Checkpointer 初始化完成: {config.redis_url}")
        except Exception as e:
            logger.error(f"AsyncRedis Checkpointer 初始化失败，回退到内存模式: {e}")
            from langgraph.checkpoint.memory import MemorySaver
            self.checkpointer = MemorySaver()

        # Agent 初始化（会在异步方法中完成）
        self.agent = None
        self._agent_initialized = False

        logger.info(
            f"RAG Agent 服务初始化完成 (ChatQwen), model={self.model_name}, summary_model={self.summary_model_name}, streaming={streaming}"
        )

    async def _initialize_agent(self):
        """异步初始化 Agent（包括 MCP 工具）"""
        if self._agent_initialized:
            return

        # 1. 初始化 Checkpointer（如果需要异步 setup）
        if isinstance(self.checkpointer, AsyncRedisSaver):
            try:
                await self.checkpointer.setup()
                logger.info("AsyncRedis Checkpointer setup 成功")
            except Exception as e:
                logger.error(f"AsyncRedis Checkpointer setup 失败: {e}")

        # 2. 使用全局 MCP 客户端管理器（带重试拦截器）
        mcp_client = await get_mcp_client_with_retry()

        # 获取 MCP 工具
        mcp_tools = await mcp_client.get_tools()
        logger.info(f"成功加载 {len(mcp_tools)} 个 MCP 工具")

        # 将 MCP 工具添加到实例变量中
        self.mcp_tools = mcp_tools

        # 合并所有工具
        all_tools = self.tools + self.mcp_tools

        self.agent = create_agent(
            self.model,
            tools=all_tools,
            middleware=[
                SummarizationMiddleware(
                    model=self.summary_model,
                    trigger=("tokens", 12000),
                    keep=("tokens", 4000),
                )
            ],
            checkpointer=self.checkpointer,
        )

        self._agent_initialized = True


        if all_tools:
            tool_names = [tool.name if hasattr(tool, "name") else str(tool) for tool in all_tools]
            logger.info(f"可用工具列表: {', '.join(tool_names)}")

    def _build_system_prompt(self) -> str:
        """
        构建系统提示词

        注意：LangChain 框架会自动将工具信息传递给 LLM，
        因此系统提示词中无需列举具体的工具列表。

        Returns:
            str: 系统提示词
        """
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

    async def query(
        self,
        question: str,
        session_id: str,
    ) -> str:
        """
        非流式处理用户问题（一次性返回完整答案）

        Args:
            question: 用户问题
            session_id: 会话ID（作为 thread_id）

        Returns:
            str: 完整答案
        """
        try:
            await self._initialize_agent()

            # 获取历史记录，判断是否为新会话
            history = await self.get_session_history(session_id)
            
            # 构建消息列表
            messages = []
            if not history:
                # 只有新会话才发送系统提示词，避免历史记录中重复出现
                messages.append(SystemMessage(content=self.system_prompt))
                logger.info(f"[会话 {session_id}] 开启新会话，添加系统提示词")
            else:
                logger.info(f"[会话 {session_id}] 恢复已有会话，当前历史记录长度: {len(history)}")

            messages.append(HumanMessage(content=question))

            # 构建 Agent 输入
            agent_input = {"messages": messages}

            # 配置 thread_id（用于会话持久化）
            config_dict = {
                "configurable": {
                    "thread_id": session_id
                }
            }

            result = await self.agent.ainvoke(
                input=agent_input,
                config=config_dict,
            )

            messages_result = result.get("messages", [])
            if messages_result:
                tool_calls = []
                for msg in messages_result:
                    msg_tool_calls = getattr(msg, "tool_calls", None)
                    if not msg_tool_calls:
                        continue
                    for tc in msg_tool_calls:
                        if isinstance(tc, dict):
                            tool_calls.append({
                                "name": tc.get("name", "unknown"),
                                "args": tc.get("args", {}),
                                "id": tc.get("id", ""),
                            })

                if tool_calls:
                    tool_names = [tc["name"] for tc in tool_calls]
                    logger.info(f"[会话 {session_id}] Agent 调用了工具: {tool_names}")

                answer = ""
                for msg in reversed(messages_result):
                    content = getattr(msg, "content", None)
                    if isinstance(content, str) and content.strip():
                        answer = content
                        break
                    if isinstance(content, list):
                        text_parts = [
                            block.get("text", "")
                            for block in content
                            if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
                        ]
                        if text_parts:
                            answer = "".join(text_parts)
                            break

                if not answer:
                    last_message = messages_result[-1]
                    answer = str(last_message)

                logger.info(f"[会话 {session_id}] RAG Agent 查询完成（非流式）")
                return answer

            logger.warning(f"[会话 {session_id}] Agent 返回结果为空")
            return ""

        except Exception as e:
            logger.error(f"[会话 {session_id}] RAG Agent 查询失败（非流式）: {e}")
            raise

    async def query_stream(
        self,
        question: str,
        session_id: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式处理用户问题（逐步返回答案片段）

        Args:
            question: 用户问题
            session_id: 会话ID（作为 thread_id）

        Yields:
            Dict[str, Any]: 包含流式数据的字典
                - type: "content" | "tool_call" | "complete" | "error"
                - data: 具体内容
        """
        try:
            await self._initialize_agent()

            # 获取历史记录，判断是否为新会话
            history = await self.get_session_history(session_id)
            
            # 构建消息列表
            messages = []
            if not history:
                # 只有新会话才发送系统提示词，避免历史记录中重复出现
                messages.append(SystemMessage(content=self.system_prompt))
                logger.info(f"[会话 {session_id}] 开启新会话，添加系统提示词")
            else:
                logger.info(f"[会话 {session_id}] 恢复已有会话，当前历史记录长度: {len(history)}")

            messages.append(HumanMessage(content=question))

            # 构建 Agent 输入
            agent_input = {"messages": messages}

            # 配置 thread_id（用于会话持久化）
            config_dict = {
                "configurable": {
                    "thread_id": session_id
                }
            }

            async for token, metadata in self.agent.astream(
                input=agent_input,
                config=config_dict,
                stream_mode="messages",
            ):
                node_name = metadata.get('langgraph_node', 'unknown') if isinstance(metadata, dict) else 'unknown'
                message_type = type(token).__name__

                if message_type in ("AIMessage", "AIMessageChunk"):
                    content_blocks = getattr(token, 'content_blocks', None)

                    if content_blocks and isinstance(content_blocks, list):
                        for block in content_blocks:
                            if isinstance(block, dict) and block.get('type') == 'text':
                                text_content = block.get('text', '')
                                if text_content:
                                    yield {
                                        "type": "content",
                                        "data": text_content,
                                        "node": node_name
                                    }

            logger.info(f"[会话 {session_id}] RAG Agent 查询完成（流式）")
            yield {"type": "complete"}

        except Exception as e:
            logger.error(f"[会话 {session_id}] RAG Agent 查询失败（流式）: {e}")
            yield {
                "type": "error",
                "data": str(e)
            }
            raise

    async def get_session_history(self, session_id: str) -> list:
        """
        获取会话历史（从 Agent 状态中读取）

        Args:
            session_id: 会话ID（即 thread_id）

        Returns:
            list: 消息历史列表 [{"role": "user|assistant", "content": "...", "timestamp": "..."}]
        """
        try:
            await self._initialize_agent()
            
            # 配置 thread_id
            config = {"configurable": {"thread_id": session_id}}
            
            # 获取该 thread 的当前状态
            state = await self.agent.aget_state(config)
            
            if not state or not state.values or "messages" not in state.values:
                logger.info(f"获取会话历史: {session_id}, 消息数量: 0")
                return []
            
            messages = state.values["messages"]
            
            # 转换为前端需要的格式
            history = []
            for msg in messages:
                # 跳过系统消息
                if isinstance(msg, SystemMessage):
                    continue
                    
                role = "user" if isinstance(msg, HumanMessage) else "assistant"
                content = msg.content if hasattr(msg, 'content') else str(msg)
                
                # 尝试从元数据中获取时间戳
                timestamp = msg.additional_kwargs.get('timestamp')
                
                if not timestamp:
                    from datetime import datetime
                    timestamp = datetime.now().isoformat()
                    
                history.append({
                    "role": role,
                    "content": content,
                    "timestamp": timestamp
                })
            
            logger.info(f"获取会话历史: {session_id}, 消息数量: {len(history)}")
            return history
            
        except Exception as e:
            logger.error(f"获取会话历史失败: {session_id}, 错误: {e}")
            return []

    def clear_session(self, session_id: str) -> bool:
        """
        清空会话历史

        Args:
            session_id: 会话ID（即 thread_id）

        Returns:
            bool: 是否成功
        """
        try:
            # 使用同步客户端进行清理
            import redis
            sync_redis = redis.from_url(config.redis_url, decode_responses=True)
            
            # RedisSaver 的键通常以 checkpoint:thread_id 开头
            pattern = f"checkpoint:{session_id}:*"
            keys = sync_redis.keys(pattern)
            if keys:
                sync_redis.delete(*keys)
            logger.info(f"已从 Redis 中清除会话历史: {session_id}, 删除了 {len(keys)} 个键")
            
            return True
            
        except Exception as e:
            logger.error(f"清空会话历史失败: {session_id}, 错误: {e}")
            return False

    async def cleanup(self):
        """清理资源"""
        try:
            logger.info("清理 RAG Agent 服务资源...")
            # MCP 客户端由全局管理器统一管理，无需手动清理
            logger.info("RAG Agent 服务资源已清理")
        except Exception as e:
            logger.error(f"清理资源失败: {e}")


# 全局单例 - 启用流式输出
rag_agent_service = RagAgentService(streaming=True)
