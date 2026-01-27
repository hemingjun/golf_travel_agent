"""ReAct Agent 图定义

使用 LangGraph 的 create_react_agent 构建单一 ReAct Agent。
运行时通过 config["configurable"] 传递 trip_id/customer_id 等参数。
"""

import sqlite3
from typing import Any

from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.prebuilt import create_react_agent

from .utils.llm_wrapper import create_self_healing_llm
from .prompts import prompt_factory
from .state import ReactAgentState
from .tools import get_all_tools
from .utils.debug import debug_print


def create_graph(
    model: str = "gemini-3-flash-preview",
    checkpointer: Any = None,
    db_path: str = "/app/data/checkpoints.db",
):
    """创建可复用的 ReAct Agent 图（动态配置模式）

    此函数创建一个无状态的图，trip_id/customer_id 在运行时通过
    config["configurable"] 传递，而非构建时绑定。

    调用示例：
        graph.invoke(
            {"messages": [HumanMessage(content="今天几点开球？")]},
            config={
                "configurable": {
                    "thread_id": "session_123",
                    "trip_id": "notion-page-id",
                    "customer_id": "",  # 空字符串 = 管理员模式
                    "current_date": "2026年01月22日",
                }
            }
        )

    Args:
        model: Gemini 模型 ID
        checkpointer: 检查点管理器（"memory", "sqlite" 或实例）
        db_path: SQLite 数据库路径（仅当 checkpointer="sqlite" 时使用）

    Returns:
        编译后的 LangGraph 图（可复用）
    """
    debug_print(f"[Graph] 创建动态配置图: model={model}")

    llm = create_self_healing_llm(
        model=model,
        temperature=0.1,
        request_timeout=60,
        max_retries=2,
    )

    # 工具从 config["configurable"] 读取 trip_id/customer_id
    tools = get_all_tools()
    debug_print(f"[Graph] 已注册 {len(tools)} 个工具")

    if checkpointer == "sqlite":
        conn = sqlite3.connect(db_path, check_same_thread=False)
        checkpointer = SqliteSaver(conn)
    elif checkpointer == "async_sqlite":
        checkpointer = AsyncSqliteSaver.from_conn_string(db_path)
    elif checkpointer == "memory":
        checkpointer = MemorySaver()

    # 使用 RunnableLambda 包装 prompt_factory，自动传递 config 给双参数函数
    compiled = create_react_agent(
        model=llm,
        tools=tools,
        state_schema=ReactAgentState,
        prompt=RunnableLambda(prompt_factory),  # LangGraph 1.0: 用 RunnableLambda 包装
        checkpointer=checkpointer,
    )

    debug_print("[Graph] 动态配置图创建完成")
    return compiled


# 单例模式（用于服务端）
_graph_instance = None


def get_graph(
    model: str = "gemini-3-flash-preview",
    checkpointer: Any = "sqlite",
    db_path: str = "/app/data/checkpoints.db",
):
    """获取或创建单例图实例

    适用于服务端场景，确保只创建一个图实例。

    Args:
        model: Gemini 模型 ID
        checkpointer: 检查点管理器
        db_path: SQLite 数据库路径

    Returns:
        单例 LangGraph 图
    """
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = create_graph(
            model=model,
            checkpointer=checkpointer,
            db_path=db_path,
        )
    return _graph_instance
