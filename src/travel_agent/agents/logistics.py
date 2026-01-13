"""Logistics Agent - 物流相关查询"""

from langchain_core.messages import AIMessage

from ..graph.state import GraphState
from ..tools.logistics import get_logistics_arrangements


def logistics_agent(state: GraphState) -> dict:
    """处理物流相关任务

    返回格式遵循增量更新原则：
    - trip_data: 只包含本 Agent 负责的字段
    - messages: 添加进度消息通知 Supervisor
    """
    trip_id = state["trip_id"]

    # 调用工具获取数据
    arrangements = get_logistics_arrangements(trip_id)

    # 构建增量更新
    trip_data_update = {
        "logistics": arrangements,
        "logistics_count": len(arrangements),
    }

    # 构建进度消息
    if arrangements:
        summary = f"[Logistics Agent] 已获取 {len(arrangements)} 条物流安排"
        details = []
        for a in arrangements:
            props = a.get("properties", {})
            date = props.get("日期", "")
            time = props.get("出发时间", "")
            dest = props.get("目的地", "")
            vehicle = props.get("车型", "")
            details.append(f"- {date} {time}: {dest} ({vehicle})")
        summary += "\n" + "\n".join(details)
    else:
        summary = "[Logistics Agent] 暂无物流安排数据"

    progress_msg = AIMessage(content=summary, name="logistics_agent")

    return {
        "trip_data": trip_data_update,
        "messages": [progress_msg],
    }
