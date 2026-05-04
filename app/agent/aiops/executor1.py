"""
Executor1 子图执行器

使用 LangGraph 显式构建 agent/tools 循环子图：
- agent 节点负责模型推理与工具调用决策
- tools 节点负责执行实际工具调用
- 当模型不再发起工具调用时结束子图
"""

from typing import Annotated, Any, Dict, Sequence, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_qwq import ChatQwen
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from loguru import logger

from app.agent.mcp_client import get_mcp_client_with_retry
from app.config import config as app_config
from app.tools import get_current_time, retrieve_knowledge, retrieve_past_diagnoses

from .state import PlanExecuteState


class ExecutorInternalState(TypedDict):
    """Executor 内部子图状态，只维护消息序列。"""

    messages: Annotated[Sequence[BaseMessage], add_messages]


def _extract_result_from_messages(messages: Sequence[BaseMessage]) -> str:
    """从子图最终消息中提取可展示的文本结果。"""

    for msg in reversed(messages):
        if not isinstance(msg, AIMessage):
            continue
        content = getattr(msg, "content", None)
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            text_parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
            ]
            if text_parts:
                return "".join(text_parts)
    if messages:
        return str(messages[-1])
    return ""


async def executor1(
    state: PlanExecuteState, 
    config: RunnableConfig = None, 
    checkpointer=None
) -> Dict[str, Any]:
    """执行计划中的一个步骤，并将结果写回 PlanExecuteState。"""

    logger.info("=== Executor1：执行步骤（子图模式）===")

    plan = state.get("plan", [])
    if not plan:
        logger.info("计划为空，跳过执行")
        return {}

    task = plan[0]
    logger.info(f"当前任务: {task}")

    try:
        # 1) 组装工具：本地工具 + MCP 工具
        local_tools = [get_current_time, retrieve_knowledge, retrieve_past_diagnoses]
        mcp_client = await get_mcp_client_with_retry()
        mcp_tools = await mcp_client.get_tools()
        all_tools = local_tools + mcp_tools
        logger.info(f"可用工具数量: 本地 {len(local_tools)} + MCP {len(mcp_tools)}")

        llm = ChatQwen(
            model=app_config.rag_model,
            api_key=app_config.dashscope_api_key,
            temperature=0,
        )
        llm_with_tools = llm.bind_tools(all_tools)

        async def agent_node(internal_state: ExecutorInternalState) -> Dict[str, Any]:
            # agent 节点：让模型基于当前消息继续推理
            response = await llm_with_tools.ainvoke(internal_state["messages"])
            return {"messages": [response]}

        def should_use_tools(internal_state: ExecutorInternalState) -> str:
            # 条件路由：若最新 AIMessage 含 tool_calls，则进入 tools 节点
            messages = internal_state.get("messages", [])
            if not messages:
                return END
            last_msg = messages[-1]
            tool_calls = getattr(last_msg, "tool_calls", None)
            return "tools" if tool_calls else END

        workflow = StateGraph(ExecutorInternalState)
        workflow.add_node("agent", agent_node)
        workflow.add_node("tools", ToolNode(all_tools))
        workflow.set_entry_point("agent")
        # add_conditional_edges(起点节点, 条件函数, 路由映射)
        # 这里表示：从 agent 出发，执行 should_use_tools(state)。
        # - 返回 "tools" => 跳转到 tools 节点执行工具
        # - 返回 END     => 结束子图
        # 这个映射里只有两个分支，因此没有“额外默认分支”。
        workflow.add_conditional_edges("agent", should_use_tools, {"tools": "tools", END: END})
        workflow.add_edge("tools", "agent")
        
        # 编译子图，显式绑定传入的 checkpointer
        graph = workflow.compile(checkpointer=checkpointer)

        # 2) 初始化子图消息：系统约束 + 当前步骤任务
        initial_messages: Sequence[BaseMessage] = [
            SystemMessage(
                content=(
                    "你是一个能力强大的助手，负责执行具体的任务步骤。\n\n"
                    "你可以使用各种工具来完成任务。对于每个步骤：\n"
                    "1. 理解步骤的目标\n"
                    "2. 选择合适的工具，如果已经指定了工具，则使用指定的工具\n"
                    "3. 调用工具获取信息\n"
                    "4. 返回执行结果\n\n"
                    "注意：\n"
                    "- 如果工具调用失败，请说明失败原因\n"
                    "- 不要编造数据，只返回实际获取的信息\n"
                    "- 执行结果要清晰、准确\n"
                    "- 专注于当前步骤，不要考虑其他任务"
                )
            ),
            HumanMessage(content=f"请执行以下任务: {task}"),
        ]

        # 3) 运行子图并提取最终文本结果
        # 透传父图的 config，使子图共享 thread_id 并在 Redis 中创建子命名空间
        internal_result = await graph.ainvoke(
            {"messages": initial_messages},
            config=config
        )
        result_messages = internal_result.get("messages", [])
        result = _extract_result_from_messages(result_messages)
        logger.info(f"步骤执行完成，结果长度: {len(result)}")

        return {
            "plan": plan[1:],
            "past_steps": [(task, result)],
        }
    except Exception as e:
        # 异常兜底：记录失败结果，保证流程可继续推进
        logger.error(f"执行步骤失败: {e}", exc_info=True)
        return {
            "plan": plan[1:],
            "past_steps": [(task, f"执行失败: {str(e)}")],
        }
