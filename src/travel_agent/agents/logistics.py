"""Logistics Agent - 物流相关查询"""

from langchain_core.messages import AIMessage

from ..graph.state import GraphState
from ..tools.logistics import get_logistics_arrangements


def logistics_agent(state: GraphState) -> dict:
    """处理物流相关任务

    返回格式遵循增量更新原则：
    - trip_data: 只包含本 Agent 负责的字段（英文 Key）
    - messages: 添加进度消息通知 Supervisor
    """
    trip_id = state["trip_id"]

    # 调用工具获取数据
    arrangements = get_logistics_arrangements(trip_id)

    # 1. 转换 Key (中文 -> 英文)，便于 Analyst 进行逻辑计算
    logistics_formatted = []
    for a in arrangements:
        props = a.get("properties", {})
        item = {
            "id": a.get("id"),
            "date": props.get("日期", ""),
            "departure_time": props.get("出发时间", ""),
            "origin": props.get("出发地", ""),
            "destination": props.get("目的地", ""),
            "vehicle_type": props.get("车型", ""),
            "pax": props.get("人数", ""),
            "duration_mins": props.get("行程时长(分钟)", ""),
            "notes": props.get("备注", ""),
        }
        logistics_formatted.append(item)

    # 2. 按日期+时间排序（空值排最后）
    logistics_formatted.sort(
        key=lambda x: (x["date"] or "9999", x["departure_time"] or "99:99")
    )

    # 3. 构建增量更新
    trip_data_update = {
        "logistics": logistics_formatted,
        "logistics_count": len(arrangements),
    }

    # 4. 构建中文摘要供 Supervisor 查看
    if arrangements:
        summary = f"[Logistics Agent] 已获取 {len(arrangements)} 条物流安排"
        details = []
        for item in logistics_formatted:
            date = item.get("date", "")
            time = item.get("departure_time", "")
            origin = item.get("origin", "")
            dest = item.get("destination", "")
            vehicle = item.get("vehicle_type", "")
            details.append(f"- [{date} {time}] {origin} -> {dest} ({vehicle})")
        summary += "\n" + "\n".join(details)
    else:
        summary = "[Logistics Agent] 暂无物流安排数据"

    progress_msg = AIMessage(content=summary, name="logistics_agent")

    return {
        "trip_data": trip_data_update,
        "messages": [progress_msg],
    }
