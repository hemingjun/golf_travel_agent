"""Itinerary Agent - 行程大纲聚合查询"""

from langchain_core.messages import AIMessage

from ..graph.state import GraphState
from ..tools.trip import get_trip_info, get_trip_events
from ..debug import print_node_enter, print_routing, print_trip_data_update


def itinerary_agent(state: GraphState) -> dict:
    """处理行程大纲相关任务

    返回格式遵循增量更新原则：
    - trip_data: 只包含本 Agent 负责的字段
    - messages: 添加进度消息通知 Supervisor
    """
    # 节点入口标识
    print_node_enter("itinerary_agent")

    trip_id = state["trip_id"]

    # 获取行程基本信息
    trip_info = get_trip_info(trip_id)

    # 获取行程事件
    events = get_trip_events(trip_id)

    # 转换行程信息为 LLM 友好的字段名
    props = trip_info.get("properties", {})
    trip_info_formatted = {
        "行程名称": props.get("Name", "未知行程"),
        "项目日期": props.get("项目日期", ""),
        "项目类型": props.get("项目类型", ""),
        "人数": props.get("人数", 0),
    }

    # 转换事件列表为 LLM 友好的字段名（不包含 Notion Title，客户不需要看到）
    events_formatted = []
    for e in events:
        e_props = e.get("properties", {})
        events_formatted.append({
            "日期": e_props.get("日期", ""),
            "事件类型": e_props.get("事件类型", ""),
            "事件内容": e_props.get("事件内容", ""),
            "开球时间": e_props.get("Teetime", ""),
        })

    # 构建增量更新
    trip_data_update = {
        "trip_info": trip_info_formatted,
        "events": events_formatted,
        "events_count": len(events),
    }

    # 构建进度消息
    summary = f"[Itinerary Agent] 行程信息：{trip_info_formatted['行程名称']}\n"
    summary += f"- 日期：{trip_info_formatted['项目日期']}\n"
    summary += f"- 类型：{trip_info_formatted['项目类型']}\n"
    summary += f"- 人数：{trip_info_formatted['人数']}\n"
    summary += f"- 事件数：{len(events)} 个\n"

    if events_formatted:
        summary += "\n事件列表：\n"
        for item in events_formatted:
            e_date = item.get("日期", "")
            e_type = item.get("事件类型", "")
            e_content = item.get("事件内容", "")
            summary += f"- {e_date} [{e_type}] {e_content}\n"

    progress_msg = AIMessage(content=summary, name="itinerary_agent")

    # 展示数据更新
    print_trip_data_update("trip_info", trip_info_formatted)
    print_trip_data_update("events", events_formatted)
    print_routing("itinerary_agent", "supervisor", f"获取行程信息 + {len(events)} 个事件")

    return {
        "trip_data": trip_data_update,
        "messages": [progress_msg],
    }
