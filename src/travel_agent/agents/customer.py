"""Customer Agent - 客户信息查询"""

from langchain_core.messages import AIMessage

from ..graph.state import GraphState
from ..tools.customer import (
    get_customer_info,
    get_customer_relatives,
    get_customer_trips,
)
from ..debug import print_node_enter, print_routing, print_trip_data_update


def customer_agent(state: GraphState) -> dict:
    """处理客户信息相关任务

    【安全】只能获取当前登录客户 (customer_id) 的数据
    【标准化】输出英文 Key，便于 Planner/Analyst 处理
    """
    # 节点入口标识
    print_node_enter("customer_agent")

    customer_id = state.get("customer_id")

    if not customer_id:
        return {
            "messages": [
                AIMessage(
                    content="[Customer Agent] 错误：未提供客户 ID",
                    name="customer_agent",
                )
            ],
        }

    # 1. 获取原始数据
    raw_info = get_customer_info(customer_id)
    if not raw_info:
        return {
            "messages": [
                AIMessage(
                    content="[Customer Agent] 未找到客户信息",
                    name="customer_agent",
                )
            ],
        }

    raw_relatives = get_customer_relatives(customer_id)
    raw_trips = get_customer_trips(customer_id)

    # 2. 构建客户档案（工具函数已返回英文 key）
    customer_profile = {
        "name": raw_info.get("name", "未知客户"),
        "country": raw_info.get("country", []),
        "handicap": raw_info.get("handicap"),  # 保持 None 或数字
        "diet": raw_info.get("dietary_preferences", ""),
        "service_notes": raw_info.get("service_requirements", ""),
        "membership_level": raw_info.get("membership_type", []),
        # 亲友列表（工具函数已返回英文 key）
        "relatives": [
            {"id": r.get("id"), "name": r.get("name")}
            for r in raw_relatives
        ],
        # 行程列表（工具函数已返回英文 key）
        "trip_history": [
            {
                "trip_id": t.get("id"),
                "trip_name": t.get("name"),
                "date": t.get("date"),
            }
            for t in raw_trips
        ],
    }

    # 3. 构建简洁的进度消息
    name = customer_profile["name"]
    rel_count = len(customer_profile["relatives"])
    trip_count = len(customer_profile["trip_history"])

    summary = f"[Customer Agent] 已加载客户 {name} 的档案"
    if rel_count > 0 or trip_count > 0:
        parts = []
        if rel_count > 0:
            parts.append(f"{rel_count} 位亲友")
        if trip_count > 0:
            parts.append(f"{trip_count} 个历史行程")
        summary += f"，关联 {'及'.join(parts)}。"
    else:
        summary += "。"

    # 展示数据更新
    print_trip_data_update("customer", customer_profile)
    print_routing("customer_agent", "supervisor", f"加载客户 {name} 档案")

    return {
        "trip_data": {"customer": customer_profile},
        "messages": [AIMessage(content=summary, name="customer_agent")],
    }
