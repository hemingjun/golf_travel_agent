"""Hotel Agent - 酒店相关查询 (含快速失败机制)

Principle B: Fail Fast & Explicit Feedback
- 检测请求是否超出能力范围
- 返回结构化失败信号，建议正确的 Agent
"""

import json
from langchain_core.messages import AIMessage, HumanMessage

from ..graph.state import GraphState
from ..tools.hotel import get_hotel_bookings, get_hotel_details
from ..debug import debug_print, print_node_enter, print_routing, print_trip_data_update


# ==================== 能力边界定义 ====================

# Hotel Agent 能处理的字段（内部数据库字段）
SUPPORTED_FIELDS = frozenset([
    "预订", "房型", "房间", "入住", "退房", "check-in", "check-out",
    "确认号", "confirmation", "床型", "景观", "早餐", "地址", "电话",
    "星级", "酒店名", "hotel", "住宿", "房价", "价格",
])

# 需要外部搜索的字段（超出能力范围）
EXTERNAL_FIELDS = frozenset([
    "评价", "评分", "reviews", "rating", "口碑", "推荐",
    "攻略", "tips", "建议", "怎么样", "好不好",
    "天气", "weather", "气温", "下雨",
    "交通", "怎么去", "路线", "距离多远",
    "周边", "附近", "餐厅", "美食",
    "汇率", "换算", "多少钱",
])


def _detect_capability_boundary(state: GraphState) -> tuple[bool, str, str]:
    """检测请求是否超出 Hotel Agent 的能力边界

    重要：只根据 Supervisor 分配的指令判断，不检测用户原始问题。
    这确保当 Supervisor 指派 "获取酒店名称" 时，即使用户问的是 "评价"，
    Agent 也能正确执行获取酒店信息的任务。

    Returns:
        (is_out_of_scope, reason, suggested_agent)
    """
    # 只检测 Supervisor 分配的任务指令
    supervisor_instructions = state.get("supervisor_instructions", "").lower()

    # 如果没有明确指令，不拒绝执行
    if not supervisor_instructions:
        return False, "", ""

    # 检测指令中是否包含外部字段（仅对指令负责，不对用户问题负责）
    for field in EXTERNAL_FIELDS:
        if field in supervisor_instructions:
            reason = f"Supervisor 指令涉及 '{field}'，属于公开信息，需要搜索引擎"

            # 推断建议的 Agent
            if field in ("天气", "weather", "气温", "下雨"):
                return True, reason, "weather_agent"
            else:
                return True, reason, "search_agent"

    # 检测 Planner 的数据源指令（仅对纯 PUBLIC_WEB 拒绝）
    refined_plan = state.get("refined_plan", "")
    if refined_plan:
        try:
            plan = json.loads(refined_plan)
            data_source = plan.get("data_source", "")
            # 只有纯 PUBLIC_WEB 才拒绝，MIXED 类型允许执行
            if data_source == "PUBLIC_WEB":
                return True, "Planner 指定数据源为 PUBLIC_WEB", "search_agent"
        except (json.JSONDecodeError, TypeError):
            pass

    return False, "", ""


def hotel_agent(state: GraphState) -> dict:
    """处理酒店相关任务

    实现 Principle B: Fail Fast & Explicit Feedback
    1. 首先检测请求是否在能力范围内
    2. 超出范围则立即返回 FAILURE 信号
    3. 在范围内则执行正常查询

    通过二次查询获取完整酒店信息：
    1. 从酒店组件获取预订记录（包含酒店 relation ID）
    2. 通过酒店 ID 查询酒店主数据库获取详细信息

    【安全】如果提供了 customer_id，只返回该客户的酒店预订
    """

    # 节点入口标识
    print_node_enter("hotel_agent")

    # === Principle B: 边界检测（优先执行）===
    is_out_of_scope, reason, suggested_agent = _detect_capability_boundary(state)

    if is_out_of_scope:
        debug_print(f"[Hotel Agent] 能力边界检测: {reason}")

        # 返回结构化失败信号
        failure_response = {
            "status": "FAILURE",
            "reason": "MISSING_CAPABILITY",
            "message": f"[Hotel Agent] {reason}",
            "suggested_agent": suggested_agent,
        }

        failure_msg = AIMessage(
            content=(
                f"[Hotel Agent] FAILURE - MISSING_CAPABILITY\n"
                f"原因: {reason}\n"
                f"建议: 请将此请求路由到 {suggested_agent}"
            ),
            name="hotel_agent"
        )

        print_routing("hotel_agent", "supervisor", f"FAILURE - {reason}")

        return {
            "trip_data": {"hotel_agent_status": failure_response},
            "messages": [failure_msg],
        }

    # === 正常流程：查询内部数据库 ===
    trip_id = state["trip_id"]
    customer_id = state.get("customer_id")

    # 1. 获取酒店预订列表（如果有 customer_id 则过滤）
    bookings = get_hotel_bookings(trip_id, customer_id)

    # 2. 转换为英文 Key，并通过酒店 ID 获取详细信息
    hotel_formatted = []
    for b in bookings:
        props = b.get("properties", {})

        # 获取酒店 relation ID 并查询详情
        hotel_ids = props.get("酒店", [])
        hotel_info = {}
        if hotel_ids:
            debug_print(f"[Hotel Agent] 查询酒店详情: {hotel_ids[0]}")
            hotel_info = get_hotel_details(hotel_ids[0]) or {}

        # 合并预订信息和酒店详情
        # 注意：hotel_info 使用英文 key（来自 transform_props）
        #       props 是原始 Notion 数据，使用中文 key
        item = {
            "id": b.get("id"),
            # 酒店基本信息（来自酒店主数据库，已转换为英文 key）
            "hotel_name": hotel_info.get("name_cn") or hotel_info.get("name_en") or "未知酒店",
            "hotel_name_en": hotel_info.get("name_en", ""),
            "address": hotel_info.get("address", ""),
            "phone": hotel_info.get("phone", ""),
            "star_rating": hotel_info.get("star_rating", ""),
            "breakfast_info": hotel_info.get("breakfast", ""),
            "hotel_check_in_time": hotel_info.get("check_in_time", ""),
            "hotel_check_out_time": hotel_info.get("check_out_time", ""),
            "hotel_notes": hotel_info.get("check_in_notes", ""),
            "hotel_website": hotel_info.get("website", ""),
            # 预订信息（来自酒店组件原始 Notion 数据）
            "check_in": props.get("入住日期", ""),
            "check_out": props.get("退房日期", ""),
            "room_type": props.get("房型", ""),
            "room_category": props.get("房间等级", ""),
            "view": props.get("景观", ""),
            "confirmation": props.get("confirmation #", ""),
            "booking_notes": props.get("备注", ""),
        }
        hotel_formatted.append(item)

    # 3. 按入住日期排序
    hotel_formatted.sort(key=lambda x: x["check_in"] or "9999")

    # 4. 构建增量更新
    trip_data_update = {
        "hotel_bookings": hotel_formatted,
        "hotel_count": len(hotel_formatted),
    }

    # 5. 构建进度消息
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

    # 展示数据更新
    print_trip_data_update("hotel_bookings", hotel_formatted)
    print_routing("hotel_agent", "supervisor", f"获取 {len(hotel_formatted)} 条酒店预订")

    return {
        "trip_data": trip_data_update,
        "messages": [progress_msg],
    }
