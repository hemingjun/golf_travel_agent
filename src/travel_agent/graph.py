"""ReAct Agent 图定义

使用 LangGraph 的 create_react_agent 构建单一 ReAct Agent。
"""

from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from .prompts import create_system_prompt
from .state import ReactAgentState
from .tools import create_all_tools
from .utils.debug import debug_print


def create_graph(
    trip_id: str,
    customer_id: str = "",
    customer_info: dict | None = None,
    current_date: str = "",
    model: str = "gemini-3-flash-preview",
    checkpointer: Any = None,
):
    """创建 ReAct Agent 图

    Args:
        trip_id: 行程 ID
        customer_id: 客户 ID（空字符串表示管理员模式）
        customer_info: 客户信息缓存（可选）
        current_date: 当前日期字符串
        model: Gemini 模型 ID
        checkpointer: 检查点管理器（"memory" 或 MemorySaver 实例）

    Returns:
        编译后的 LangGraph 图
    """
    debug_print(f"[Graph] 创建图: trip={trip_id[:8]}..., model={model}")

    llm = ChatGoogleGenerativeAI(
        model=model,
        temperature=0.1,  # 降低以提高工具调用稳定性
        request_timeout=60,
    )

    tools = create_all_tools(trip_id, customer_id if customer_id else None)
    debug_print(f"[Graph] 已创建 {len(tools)} 个工具")

    system_prompt = create_system_prompt(
        trip_id=trip_id,
        customer_id=customer_id,
        current_date=current_date,
        customer_info=customer_info,
    )

    if checkpointer == "memory":
        checkpointer = MemorySaver()

    compiled = create_react_agent(
        model=llm,
        tools=tools,
        state_schema=ReactAgentState,
        prompt=system_prompt,
        checkpointer=checkpointer,
    )

    debug_print("[Graph] 图创建完成")
    return compiled
