"""Hotel Agent - 酒店相关查询"""

from langchain_core.messages import AIMessage

from ..graph.state import GraphState
from ..tools.hotel import get_hotel_bookings


def _extract_notion_list_item(value, default=""):
    """处理 Notion Relation/Rollup 返回的列表或字典

    Relation 可能返回: ['酒店名'] 或 [{'id':..., 'name':...}]
    Rollup 可能返回: ['地址'] 或单个字符串
    """
    if not value:
        return default
    if isinstance(value, list):
        if not value:
            return default
        first = value[0]
        # 处理 Relation 返回的字典格式
        if isinstance(first, dict):
            return first.get("name", default)
        return str(first)
    return str(value)


def hotel_agent(state: GraphState) -> dict:
    """处理酒店相关任务

    【安全】如果提供了 customer_id，只返回该客户的酒店预订

    返回格式遵循增量更新原则：
    - trip_data: 只包含本 Agent 负责的字段（英文 Key）
    - messages: 添加进度消息通知 Supervisor
    """
    trip_id = state["trip_id"]
    customer_id = state.get("customer_id")

    # 调用工具获取数据（如果有 customer_id 则过滤）
    bookings = get_hotel_bookings(trip_id, customer_id)

    # 转换为英文 Key，供 Analyst/Weather 使用
    hotel_formatted = []
    for b in bookings:
        props = b.get("properties", {})

        # 特殊处理 Relation (酒店) 和 Rollup (地址)
        hotel_name = _extract_notion_list_item(props.get("酒店"), "未知酒店")
        address = _extract_notion_list_item(props.get("地址"), "")

        item = {
            "id": b.get("id"),
            "hotel_name": hotel_name,
            "address": address,
            "check_in": props.get("入住日期", ""),
            "check_out": props.get("退房日期", ""),
            "room_type": props.get("房型", ""),
            "room_category": props.get("房间等级", ""),
            "breakfast": props.get("早餐", ""),
            "status": props.get("预订状态", ""),
        }
        hotel_formatted.append(item)

    # 按入住日期排序
    hotel_formatted.sort(key=lambda x: x["check_in"] or "9999")

    # 构建增量更新
    trip_data_update = {
        "hotel_bookings": hotel_formatted,
        "hotel_count": len(hotel_formatted),
    }

    # 构建进度消息: - [入住] [酒店名] (房型)
    if hotel_formatted:
        summary = f"[Hotel Agent] 已获取 {len(hotel_formatted)} 条酒店预订"
        details = [
            f"- {h['check_in']} {h['hotel_name']} ({h['room_type']})"
            for h in hotel_formatted
        ]
        summary += "\n" + "\n".join(details)
    else:
        summary = "[Hotel Agent] 未找到酒店预订记录"

    progress_msg = AIMessage(content=summary, name="hotel_agent")

    return {
        "trip_data": trip_data_update,
        "messages": [progress_msg],
    }
