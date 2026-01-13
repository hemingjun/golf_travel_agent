"""LangGraph 图构建"""

from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI

from .state import GraphState
from ..agents.supervisor import supervisor_node
from ..agents.golf import golf_agent
from ..agents.hotel import hotel_agent
from ..agents.logistics import logistics_agent
from ..agents.itinerary import itinerary_agent
from ..agents.responder import final_responder


def route_next(state: GraphState) -> str:
    """根据 state.next_step 路由"""
    return state["next_step"]


def create_graph(model_name: str = "gpt-4o-mini"):
    """创建 LangGraph 图

    Args:
        model_name: LLM 模型名称

    Returns:
        编译后的图
    """
    # 初始化 LLM
    llm = ChatOpenAI(model=model_name, temperature=0)

    # 构建图
    graph = StateGraph(GraphState)

    # 添加节点
    graph.add_node("supervisor", lambda state: supervisor_node(state, llm))
    graph.add_node("golf_agent", golf_agent)
    graph.add_node("hotel_agent", hotel_agent)
    graph.add_node("logistics_agent", logistics_agent)
    graph.add_node("itinerary_agent", itinerary_agent)
    graph.add_node("final_responder", lambda state: final_responder(state, llm))

    # 设置入口
    graph.set_entry_point("supervisor")

    # Supervisor 条件路由
    graph.add_conditional_edges(
        "supervisor",
        route_next,
        {
            "golf_agent": "golf_agent",
            "hotel_agent": "hotel_agent",
            "logistics_agent": "logistics_agent",
            "itinerary_agent": "itinerary_agent",
            "final_responder": "final_responder",
            "END": END,
        },
    )

    # Worker -> Supervisor 回环
    for worker in ["golf_agent", "hotel_agent", "logistics_agent", "itinerary_agent"]:
        graph.add_edge(worker, "supervisor")

    # Final Responder -> END
    graph.add_edge("final_responder", END)

    return graph.compile()
