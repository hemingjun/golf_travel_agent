"""ReAct Agent 图定义

使用 LangGraph 的 create_react_agent 构建单一 ReAct Agent。

支持两种模式：
1. 动态配置模式（推荐）：create_graph() - 不绑定 trip_id/customer_id
   - 运行时通过 config["configurable"] 传递参数
   - 适用于多租户服务端

2. 静态配置模式（兼容）：create_graph_static() - 构建时绑定参数
   - 适用于 CLI 等单行程场景
"""

import sqlite3
from typing import Any

from langchain_core.runnables import RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.prebuilt import create_react_agent

from .prompts import create_system_prompt, prompt_factory
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

    llm = ChatGoogleGenerativeAI(
        model=model,
        temperature=0.1,
        request_timeout=60,
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


def create_graph_static(
    trip_id: str,
    customer_id: str = "",
    customer_info: dict | None = None,
    current_date: str = "",
    model: str = "gemini-3-flash-preview",
    checkpointer: Any = None,
    db_path: str = "/app/data/checkpoints.db",
):
    """创建静态绑定的 ReAct Agent 图（兼容旧代码）

    此函数保留原有的构建时绑定行为，适用于：
    - CLI 模式（单一行程）
    - 需要向后兼容的场景

    注意：新代码应优先使用 create_graph() + 动态配置模式。

    Args:
        trip_id: 行程 ID
        customer_id: 客户 ID（空字符串表示管理员模式）
        customer_info: 客户信息缓存（可选）
        current_date: 当前日期字符串
        model: Gemini 模型 ID
        checkpointer: 检查点管理器（"memory", "sqlite" 或实例）
        db_path: SQLite 数据库路径（仅当 checkpointer="sqlite" 时使用）

    Returns:
        编译后的 LangGraph 图（绑定到特定 trip）
    """
    debug_print(f"[Graph] 创建静态绑定图: trip={trip_id[:8]}..., model={model}")

    llm = ChatGoogleGenerativeAI(
        model=model,
        temperature=0.1,
        request_timeout=60,
    )

    # 静态模式仍然使用相同的工具，但通过 config 传递参数
    tools = get_all_tools()
    debug_print(f"[Graph] 已注册 {len(tools)} 个工具")

    # 静态模式使用预生成的 System Prompt
    system_prompt = create_system_prompt(
        trip_id=trip_id,
        customer_id=customer_id,
        current_date=current_date,
        customer_info=customer_info,
    )

    if checkpointer == "sqlite":
        conn = sqlite3.connect(db_path, check_same_thread=False)
        checkpointer = SqliteSaver(conn)
    elif checkpointer == "memory":
        checkpointer = MemorySaver()

    compiled = create_react_agent(
        model=llm,
        tools=tools,
        state_schema=ReactAgentState,
        prompt=system_prompt,
        checkpointer=checkpointer,
    )

    debug_print("[Graph] 静态绑定图创建完成")
    return compiled
