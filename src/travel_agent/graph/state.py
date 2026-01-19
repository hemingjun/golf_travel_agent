"""LangGraph 状态定义"""

from typing import Literal, Annotated, Any
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


# ==================== 数据槽位类型 ====================

SlotStatus = Literal["PENDING", "DISPATCHED", "FILLED", "FAILED"]


class DataSlot(TypedDict):
    """数据槽位 - 描述一个待采集的数据项

    用于 DAG 执行引擎，支持依赖关系和状态追踪
    """

    id: str  # 唯一标识，如 "req_hotel_name"
    field_name: str  # 目标字段，如 "hotel_name"
    description: str  # 任务描述，如 "获取入住酒店的具体名称"
    source_agent: str  # 执行者，如 "hotel_agent"

    # 依赖控制（支持多依赖）
    dependencies: list[str]  # 依赖的 Slot ID 列表，如 ["req_trip_dates"]

    # 状态机
    status: SlotStatus  # PENDING -> DISPATCHED -> FILLED/FAILED
    value: Any | None  # 存储获取到的结果


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


def update_procurement_plan(
    current: list[dict] | None, update: list[dict] | None
) -> list[dict]:
    """采购计划 Reducer - 支持全量替换和增量更新

    支持两种模式：
    1. 全量更新（Planner 阶段）：update[0] 有 _replace=True 标记时整体替换
    2. 增量更新（Supervisor 阶段）：按 id 匹配更新单项状态

    Args:
        current: 当前 procurement_plan
        update: 更新数据

    Returns:
        合并后的 procurement_plan
    """
    if current is None:
        current = []
    if not update:
        return current

    # 模式 1：全量替换（Planner 初始化时）
    if update and update[0].get("_replace"):
        return [{k: v for k, v in slot.items() if k != "_replace"} for slot in update]

    # 模式 2：按 id 增量更新（Supervisor 更新状态时）
    result = [slot.copy() for slot in current]  # 深拷贝
    id_to_idx = {slot["id"]: i for i, slot in enumerate(result)}

    for slot_update in update:
        slot_id = slot_update.get("id")
        if slot_id and slot_id in id_to_idx:
            idx = id_to_idx[slot_id]
            result[idx] = {**result[idx], **slot_update}

    return result


# ==================== 路由类型 ====================

RouteTarget = Literal[
    "golf_agent",
    "hotel_agent",
    "logistics_agent",
    "itinerary_agent",
    "customer_agent",
    "weather_agent",
    "search_agent",
    "analyst",
]


# ==================== 路由历史 Reducer ====================

def append_route_history(current: list, update: list) -> list:
    """追加路由历史，保留最近 10 条记录

    支持两种操作：
    1. 普通追加：直接追加新记录
    2. 更新操作：如果 update 中有 _update=True，则更新 current 最后一条
    """
    if current is None:
        current = []
    if update is None:
        return current

    result = current.copy()

    for item in update:
        if item.get("_update") and result:
            # 更新最后一条记录的 hash
            result[-1] = {
                "agent": item["agent"],
                "result_hash": item["result_hash"]
            }
        else:
            # 普通追加（清理 _update 标记）
            clean_item = {k: v for k, v in item.items() if k != "_update"}
            result.append(clean_item)

    return result[-10:]  # 只保留最近 10 条

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

    # 路由历史 (用于死锁检测)
    # 格式: [{"agent": "hotel_agent", "result_hash": "abc123"}, ...]
    route_history: Annotated[list[dict], append_route_history]

    # 采购计划 (DAG 执行引擎核心)
    # 格式: [{"id": "req_hotel_name", "field_name": "hotel_name", ...}, ...]
    procurement_plan: Annotated[list[DataSlot], update_procurement_plan]
