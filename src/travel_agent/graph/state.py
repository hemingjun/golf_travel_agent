"""LangGraph 状态定义"""

from typing import Literal, Annotated
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


# ==================== Reducer 函数 ====================


def merge_trip_data(current: dict, update: dict) -> dict:
    """合并 trip_data - 增量更新而非覆盖

    Args:
        current: 当前状态中的 trip_data
        update: Worker 返回的增量数据

    Returns:
        合并后的 trip_data
    """
    if current is None:
        current = {}
    if update is None:
        return current

    merged = current.copy()
    for key, value in update.items():
        existing = merged.get(key)

        # 两边都是列表：智能合并
        if isinstance(value, list) and isinstance(existing, list):
            # 构建 id -> index 映射，支持更新
            id_to_idx = {
                x.get("id"): i
                for i, x in enumerate(existing)
                if isinstance(x, dict) and "id" in x
            }

            for item in value:
                if isinstance(item, dict) and "id" in item:
                    item_id = item["id"]
                    if item_id in id_to_idx:
                        # ID 存在：更新（合并字段）
                        existing[id_to_idx[item_id]].update(item)
                    else:
                        # ID 不存在：追加
                        existing.append(item)
                        id_to_idx[item_id] = len(existing) - 1
                else:
                    # 简单值列表：按值去重
                    if item not in existing:
                        existing.append(item)
        else:
            # 其他类型：直接更新
            merged[key] = value

    return merged


def reset_or_increment(current: int, update: int) -> int:
    """迭代计数器 reducer - 支持重置

    - update = 0: 重置为 0（新对话开始）
    - update > 0: 累加（正常迭代）
    """
    if update == 0:
        return 0  # 重置
    return (current or 0) + update  # 累加


# ==================== 路由类型 ====================

RouteTarget = Literal[
    "golf_agent",
    "hotel_agent",
    "logistics_agent",
    "itinerary_agent",
    "customer_agent",
    "weather_agent",
    "analyst",
]

# ==================== 分析策略类型 ====================

AnalysisStrategy = Literal["TIME_FOCUSED", "SPACE_FOCUSED", "GENERAL"]


# ==================== 状态 Schema ====================


class GraphState(TypedDict):
    """图状态 - 使用 TypedDict + Annotated 实现 Reducer"""

    # 对话历史 (自动合并)
    messages: Annotated[list[BaseMessage], add_messages]

    # 行程上下文
    trip_id: str

    # 当前登录客户 ID (page_id)
    customer_id: str

    # 当前系统日期 (启动时自动设置，格式：2026年01月16日)
    current_date: str

    # 结构化数据暂存区 (增量合并)
    trip_data: Annotated[dict, merge_trip_data]

    # 路由控制
    next_step: RouteTarget
    supervisor_instructions: str

    # 迭代计数
    iteration_count: Annotated[int, reset_or_increment]

    # 分析策略 (由 Supervisor 设定)
    analysis_strategy: AnalysisStrategy

    # 分析报告 (由 Analyst 生成)
    analysis_report: str

    # Planner 输出的精炼计划 (结构化 JSON)
    refined_plan: str
