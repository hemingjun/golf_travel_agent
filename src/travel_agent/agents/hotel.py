"""Hotel Agent - 酒店相关查询"""

from langchain_core.messages import AIMessage

from ..graph.state import GraphState
from ..tools.hotel import get_hotel_bookings


def hotel_agent(state: GraphState) -> dict:
    """处理酒店相关任务

    返回格式遵循增量更新原则：
    - trip_data: 只包含本 Agent 负责的字段
    - messages: 添加进度消息通知 Supervisor
    """
    trip_id = state["trip_id"]

    # 调用工具获取数据
    bookings = get_hotel_bookings(trip_id)

    # 构建增量更新
    trip_data_update = {
        "hotel_bookings": bookings,
        "hotel_count": len(bookings),
    }

    # 构建进度消息
    if bookings:
        summary = f"[Hotel Agent] 已获取 {len(bookings)} 条酒店预订记录"
        details = []
        for b in bookings:
            props = b.get("properties", {})
            check_in = props.get("入住日期", "")
            check_out = props.get("退房日期", "")
            title = props.get("名称", "")
            room_type = props.get("房型", "")
            details.append(f"- {check_in} 至 {check_out}: {title} ({room_type})")
        summary += "\n" + "\n".join(details)
    else:
        summary = "[Hotel Agent] 未找到酒店预订记录"

    progress_msg = AIMessage(content=summary, name="hotel_agent")

    return {
        "trip_data": trip_data_update,
        "messages": [progress_msg],
    }
