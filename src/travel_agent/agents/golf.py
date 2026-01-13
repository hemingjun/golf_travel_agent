"""Golf Agent - 高尔夫相关查询"""

from langchain_core.messages import AIMessage

from ..graph.state import GraphState
from ..tools.golf import get_golf_bookings


def golf_agent(state: GraphState) -> dict:
    """处理高尔夫相关任务

    返回格式遵循增量更新原则：
    - trip_data: 只包含本 Agent 负责的字段
    - messages: 添加进度消息通知 Supervisor
    """
    trip_id = state["trip_id"]

    # 调用工具获取数据
    bookings = get_golf_bookings(trip_id)

    # 构建增量更新
    trip_data_update = {
        "golf_bookings": bookings,
        "golf_count": len(bookings),
    }

    # 构建进度消息
    if bookings:
        summary = f"[Golf Agent] 已获取 {len(bookings)} 条高尔夫预订记录"
        details = []
        for b in bookings:
            props = b.get("properties", {})
            play_date = props.get("PlayDate", "")
            tee_time = props.get("Teetime", "")
            title = props.get("名称", "")
            course = props.get("中文名", "")  # rollup 球场中文名
            details.append(f"- {play_date} {tee_time}: {title} ({course})")
        summary += "\n" + "\n".join(details)
    else:
        summary = "[Golf Agent] 未找到高尔夫预订记录"

    progress_msg = AIMessage(content=summary, name="golf_agent")

    return {
        "trip_data": trip_data_update,
        "messages": [progress_msg],
    }
