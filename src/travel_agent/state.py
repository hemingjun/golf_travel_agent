"""ReAct Agent 简化状态定义

重构后仅保留必需字段用于 checkpoint 持久化。
行程上下文 (trip_id, customer_id 等) 通过 config["configurable"] 传递。
"""

from typing import Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from langgraph.prebuilt.chat_agent_executor import RemainingSteps
from typing_extensions import TypedDict


class ReactAgentState(TypedDict):
    """ReAct Agent 简化状态 - 仅保留 checkpoint 必需字段

    字段说明：
    - messages: 对话历史，使用 add_messages reducer 自动合并
    - remaining_steps: LangGraph 内部步数控制（create_react_agent 必需）

    注意：
    - trip_id/customer_id/current_date 等上下文通过 config["configurable"] 传递
    """

    messages: Annotated[list[BaseMessage], add_messages]
    remaining_steps: RemainingSteps
