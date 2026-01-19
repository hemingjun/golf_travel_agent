"""LangGraph 图构建"""

from functools import partial

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_google_genai import ChatGoogleGenerativeAI

from .state import GraphState
from ..agents.planner import planner_node
from ..agents.supervisor import supervisor_node
from ..agents.golf import golf_agent
from ..agents.hotel import hotel_agent
from ..agents.logistics import logistics_agent
from ..agents.itinerary import itinerary_agent
from ..agents.customer import customer_agent
from ..agents.weather import weather_agent
from ..agents.analyst import analyst_node
from ..agents.responder import final_responder
from ..agents.search import search_agent


def route_next(state: GraphState) -> str:
    """根据 state.next_step 路由"""
    return state["next_step"]


def create_graph(
    smart_model: str = "gemini-2.5-pro",
    fast_model: str = "gemini-2.5-flash",
    checkpointer=None,
):
    """创建 LangGraph 图

    Args:
        smart_model: 高智商模型，用于 Planner 和 Analyst
        fast_model: 高速度模型，用于 Supervisor 和 Responder
        checkpointer: 可选的 checkpointer，传入 "memory" 使用内置 MemorySaver

    Returns:
        编译后的图
    """
    # 初始化双模型
    smart_llm = ChatGoogleGenerativeAI(
        model=smart_model, temperature=0, request_timeout=120
    )
    fast_llm = ChatGoogleGenerativeAI(
        model=fast_model, temperature=0.3, request_timeout=60
    )

    # 构建图
    graph = StateGraph(GraphState)

    # 添加节点 - 使用 partial 绑定不同的 LLM
    # 大脑组 (Smart Brain) -> smart_llm
    graph.add_node("planner", partial(planner_node, llm=smart_llm))
    graph.add_node("analyst", partial(analyst_node, llm=smart_llm))
    # 手脚组 (Fast Brain) -> fast_llm
    graph.add_node("supervisor", partial(supervisor_node, llm=fast_llm))
    graph.add_node("final_responder", partial(final_responder, llm=fast_llm))
    # Workers (无 LLM)
    graph.add_node("golf_agent", golf_agent)
    graph.add_node("hotel_agent", hotel_agent)
    graph.add_node("logistics_agent", logistics_agent)
    graph.add_node("itinerary_agent", itinerary_agent)
    graph.add_node("customer_agent", customer_agent)
    graph.add_node("weather_agent", partial(weather_agent, llm=fast_llm))
    graph.add_node("search_agent", partial(search_agent, llm=fast_llm))

    # 设置入口为 Planner
    graph.set_entry_point("planner")

    # Planner → Supervisor（固定边）
    graph.add_edge("planner", "supervisor")

    # Supervisor 条件路由（必须经过 analyst -> final_responder，不能直接 END）
    graph.add_conditional_edges(
        "supervisor",
        route_next,
        {
            "golf_agent": "golf_agent",
            "hotel_agent": "hotel_agent",
            "logistics_agent": "logistics_agent",
            "itinerary_agent": "itinerary_agent",
            "customer_agent": "customer_agent",
            "weather_agent": "weather_agent",
            "search_agent": "search_agent",
            "analyst": "analyst",
        },
    )

    # Worker -> Supervisor 回环
    for worker in ["golf_agent", "hotel_agent", "logistics_agent", "itinerary_agent", "customer_agent", "weather_agent", "search_agent"]:
        graph.add_edge(worker, "supervisor")

    # Analyst -> Final Responder（固定边）
    graph.add_edge("analyst", "final_responder")

    # Final Responder -> END
    graph.add_edge("final_responder", END)

    # 处理 checkpointer
    if checkpointer == "memory":
        checkpointer = MemorySaver()

    return graph.compile(checkpointer=checkpointer)
