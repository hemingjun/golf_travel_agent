"""Itinerary Agent - 行程大纲聚合查询"""

from langchain_core.messages import AIMessage

from ..graph.state import GraphState
from ..tools.trip import get_trip_info, get_trip_events


def itinerary_agent(state: GraphState) -> dict:
    """处理行程大纲相关任务

    返回格式遵循增量更新原则：
    - trip_data: 只包含本 Agent 负责的字段
    - messages: 添加进度消息通知 Supervisor
    """
    trip_id = state["trip_id"]

    # 获取行程基本信息
    trip_info = get_trip_info(trip_id)

    # 获取行程事件
    events = get_trip_events(trip_id)

    # 构建增量更新
    trip_data_update = {
        "trip_info": trip_info,
        "events": events,
        "events_count": len(events),
    }

    # 构建进度消息
    props = trip_info.get("properties", {})
    trip_name = props.get("Name", "未知行程")
    trip_date = props.get("项目日期", "")
    trip_type = props.get("项目类型", "")
    people_count = props.get("人数", 0)

    summary = f"[Itinerary Agent] 行程信息：{trip_name}\n"
    summary += f"- 日期：{trip_date}\n"
    summary += f"- 类型：{trip_type}\n"
    summary += f"- 人数：{people_count}\n"
    summary += f"- 事件数：{len(events)} 个\n"

    if events:
        summary += "\n事件列表：\n"
        for e in events:
            e_props = e.get("properties", {})
            e_date = e_props.get("日期", "")
            e_type = e_props.get("事件类型", "")
            e_title = e_props.get("标题", "")
            summary += f"- {e_date} [{e_type}] {e_title}\n"

    progress_msg = AIMessage(content=summary, name="itinerary_agent")

    return {
        "trip_data": trip_data_update,
        "messages": [progress_msg],
    }
