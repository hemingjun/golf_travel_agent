"""Customer Agent - 客户信息查询"""

from langchain_core.messages import AIMessage

from ..graph.state import GraphState
from ..tools.customer import (
    get_customer_info,
    get_customer_relatives,
    get_customer_trips,
)


def customer_agent(state: GraphState) -> dict:
    """处理客户信息相关任务

    【安全】只能获取当前登录客户 (customer_id) 的数据
    【标准化】输出英文 Key，便于 Planner/Analyst 处理
    """
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

    # 2. 数据清洗与映射 (中文 Key -> 英文 Key)
    customer_profile = {
        "name": raw_info.get("全名", "未知客户"),
        "country": raw_info.get("国家", []),
        "handicap": raw_info.get("差点"),  # 保持 None 或数字
        "diet": raw_info.get("饮食习惯", ""),
        "service_notes": raw_info.get("服务需求", ""),
        "membership_level": raw_info.get("会员类型", []),
        # 清洗亲友列表
        "relatives": [
            {"id": r.get("id"), "name": r.get("全名")}
            for r in raw_relatives
        ],
        # 清洗行程列表
        "trip_history": [
            {
                "trip_id": t.get("id"),
                "trip_name": t.get("名称"),
                "date": t.get("项目日期"),
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

    return {
        "trip_data": {"customer": customer_profile},
        "messages": [AIMessage(content=summary, name="customer_agent")],
    }
