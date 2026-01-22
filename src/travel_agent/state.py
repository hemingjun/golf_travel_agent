"""ReAct Agent 简化状态定义

相比原有 GraphState 的 17+ 字段，简化为仅 6 个必要字段。
所有业务数据通过工具调用直接获取，无需中间状态存储。
"""

from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from langgraph.prebuilt.chat_agent_executor import RemainingSteps
from langchain_core.messages import BaseMessage


class ReactAgentState(TypedDict):
    """ReAct Agent 状态定义

    字段说明：
    - messages: 对话历史，使用 add_messages reducer 自动合并
    - remaining_steps: LangGraph 步数控制（必需）
    - trip_id: 当前行程 ID，用于工具查询
    - customer_id: 客户 ID（可选），用于权限过滤
    - current_date: 当前日期字符串，供 LLM 参考
    - customer_info: 客户信息缓存（可选），避免重复查询
    """

    # LangGraph ReAct Agent 必需字段
    messages: Annotated[list[BaseMessage], add_messages]
    remaining_steps: RemainingSteps

    # 行程上下文
    trip_id: str
    customer_id: str  # 空字符串表示管理员模式
    current_date: str  # 格式: "2026年01月21日"

    # 可选缓存
    customer_info: dict | None
