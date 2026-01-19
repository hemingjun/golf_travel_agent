"""Supervisor Agent - DAG 执行引擎

基于依赖图谱驱动任务执行的智能调度器：
- 数据同步：检查 trip_data，自动标记已有数据的 Slot 为 FILLED
- 依赖解析：找到第一个依赖满足的 PENDING Slot
- 上下文注水：将依赖数据注入指令
- 状态追踪：管理 Slot 的状态流转
"""

import json
import hashlib
from datetime import datetime
from typing import Any
from langchain_core.messages import AIMessage
from langchain_core.language_models import BaseChatModel

from ..debug import (
    debug_print,
    print_recipe_status,
    print_node_enter,
    print_section,
    print_worker_result,
    print_dispatch,
    print_routing,
    print_completion,
    print_data_sync,
)
from ..graph.state import GraphState, AnalysisStrategy


# ==================== 字段到 trip_data 的映射 ====================

FIELD_TO_TRIP_DATA: dict[str, tuple[str, Any]] = {
    # hotel 相关
    "hotel_name": ("hotel_bookings", lambda x: x[0].get("hotel_name") if x else None),
    "hotel_address": ("hotel_bookings", lambda x: x[0].get("address") if x else None),
    "check_in": ("hotel_bookings", lambda x: x[0].get("check_in") if x else None),
    "check_out": ("hotel_bookings", lambda x: x[0].get("check_out") if x else None),
    "room_type": ("hotel_bookings", lambda x: x[0].get("room_type") if x else None),
    # golf 相关
    "course_name": ("golf_bookings", lambda x: x[0].get("course_name") if x else None),
    "tee_time": ("golf_bookings", lambda x: x[0].get("tee_time") if x else None),
    "players": ("golf_bookings", lambda x: x[0].get("players") if x else None),
    # logistics 相关
    "departure_time": ("logistics", lambda x: x[0].get("departure_time") if x else None),
    "destination": ("logistics", lambda x: x[0].get("destination") if x else None),
    "vehicle_type": ("logistics", lambda x: x[0].get("vehicle_type") if x else None),
    # itinerary 相关
    "location": ("events", lambda x: _extract_location_from_events(x)),
    "event_date": ("events", lambda x: x[0].get("event_date") if x else None),
    # weather 相关
    "weather": ("weather_report", lambda x: x if x else None),
    "weather_forecast": ("weather_report", lambda x: x if x else None),
    # search 相关
    "reviews": ("search_findings", lambda x: x if x else None),
    "ratings": ("search_findings", lambda x: x if x else None),
    "tips": ("search_findings", lambda x: x if x else None),
    # customer 相关
    "customer_name": ("customer", lambda x: x.get("name") if x else None),
    "handicap": ("customer", lambda x: x.get("handicap") if x else None),
}


def _extract_location_from_events(events: list[dict] | None) -> str | None:
    """从 events 中提取地点信息"""
    if not events:
        return None
    for event in events:
        location = event.get("location") or event.get("destination")
        if location:
            return location
    return None


# ==================== 真实数据载荷提取 ====================


def _extract_real_value(trip_data: dict, slot: dict) -> str | None:
    """从 trip_data 中提取真实数据载荷 (Payload Extraction)

    根据 Slot 的 source_agent 和 field_name 智能提取数据。
    支持多种字段名变体，提高容错性。

    Args:
        trip_data: 当前的行程数据容器
        slot: 当前处理的 Slot

    Returns:
        提取到的真实值，或 None（表示无法提取）
    """
    agent = slot.get("source_agent", "")
    field = slot.get("field_name", "")

    # === Hotel Agent 数据提取 ===
    if agent == "hotel_agent" or field in ("hotel_name", "hotel_address"):
        bookings = trip_data.get("hotel_bookings", [])
        if bookings and isinstance(bookings, list) and len(bookings) > 0:
            first_booking = bookings[0]
            # 尝试多种字段名
            for key in ("hotel_name", "name", "酒店名称", "hotel_name_cn"):
                value = first_booking.get(key)
                if value and value != "未知酒店":
                    return str(value)
            # 如果只找到 "未知酒店"，也返回它（好过占位符）
            fallback = first_booking.get("hotel_name")
            if fallback:
                return str(fallback)

    # === Golf Agent 数据提取 ===
    if agent == "golf_agent" or field in ("course_name", "tee_time"):
        bookings = trip_data.get("golf_bookings", [])
        if bookings and isinstance(bookings, list) and len(bookings) > 0:
            first_booking = bookings[0]
            if field == "tee_time":
                for key in ("tee_time", "开球时间", "time"):
                    value = first_booking.get(key)
                    if value:
                        return str(value)
            else:
                for key in ("course_name", "name", "球场名称", "course_name_cn"):
                    value = first_booking.get(key)
                    if value:
                        return str(value)

    # === Logistics Agent 数据提取 ===
    if agent == "logistics_agent" or field in ("departure_time", "destination"):
        logistics = trip_data.get("logistics", [])
        if logistics and isinstance(logistics, list) and len(logistics) > 0:
            first_item = logistics[0]
            if field == "departure_time":
                for key in ("departure_time", "出发时间", "time"):
                    value = first_item.get(key)
                    if value:
                        return str(value)
            elif field == "destination":
                for key in ("destination", "目的地", "to"):
                    value = first_item.get(key)
                    if value:
                        return str(value)

    # === Weather Agent 数据提取 ===
    if agent == "weather_agent" or field in ("weather", "weather_forecast"):
        weather = trip_data.get("weather_report")
        if weather:
            if isinstance(weather, dict):
                # 提取摘要信息
                summary = weather.get("summary") or weather.get("description")
                if summary:
                    return str(summary)[:200]
                # 或者序列化整个对象
                return json.dumps(weather, ensure_ascii=False)[:200]
            return str(weather)[:200]

    # === Customer Agent 数据提取 ===
    if agent == "customer_agent" or field in ("customer_name", "handicap"):
        customer = trip_data.get("customer", {})
        if customer:
            if field == "customer_name":
                return customer.get("name") or customer.get("姓名")
            elif field == "handicap":
                value = customer.get("handicap") or customer.get("差点")
                if value is not None:
                    return str(value)

    # === Itinerary Agent 数据提取 ===
    if agent == "itinerary_agent" or field == "location":
        events = trip_data.get("events", [])
        if events:
            location = _extract_location_from_events(events)
            if location:
                return str(location)

    # === 通用兜底：使用原有 FIELD_TO_TRIP_DATA 映射 ===
    if field in FIELD_TO_TRIP_DATA:
        key, extractor = FIELD_TO_TRIP_DATA[field]
        data = trip_data.get(key)
        if data:
            try:
                value = extractor(data)
                if value:
                    return str(value)[:500]
            except Exception as e:
                debug_print(f"[Supervisor] Extractor 失败 ({field}): {e}")

    return None


# ==================== 数据同步函数 ====================


def _normalize_field_name(field_name: str) -> str | None:
    """Schema Normalization：将变体字段名映射到标准字段名

    解决 Planner 生成的字段名与硬编码映射不一致的问题。
    例如: hotel_name_cn, hotel_name_en, 酒店名称 → hotel_name

    Returns:
        标准化后的字段名，或 None（无法识别）
    """
    field_lower = field_name.lower()

    # Hotel 相关字段模糊匹配
    if "hotel" in field_lower and ("name" in field_lower or "名称" in field_lower or "名字" in field_lower):
        return "hotel_name"
    if "hotel" in field_lower and ("address" in field_lower or "地址" in field_lower):
        return "hotel_address"
    if "酒店" in field_name and ("名" in field_name):
        return "hotel_name"

    # Golf/Course 相关字段模糊匹配
    if ("golf" in field_lower or "course" in field_lower or "球场" in field_name) and \
       ("name" in field_lower or "名称" in field_lower or "名字" in field_lower):
        return "course_name"
    if "tee" in field_lower or "开球" in field_name:
        return "tee_time"

    # Logistics 相关字段模糊匹配
    if "departure" in field_lower or "出发" in field_name:
        return "departure_time"
    if "destination" in field_lower or "目的地" in field_name:
        return "destination"

    # Weather 相关字段模糊匹配
    if "weather" in field_lower or "天气" in field_name:
        return "weather"

    # Location 相关字段模糊匹配
    if "location" in field_lower or "地点" in field_name or "位置" in field_name:
        return "location"

    # Customer 相关字段模糊匹配
    if ("customer" in field_lower or "客户" in field_name) and ("name" in field_lower or "姓名" in field_name):
        return "customer_name"
    if "handicap" in field_lower or "差点" in field_name:
        return "handicap"

    return None


def _sync_with_trip_data(state: GraphState) -> list[dict]:
    """数据同步：检查 trip_data，将已有数据的 PENDING Slot 更新为 FILLED

    遍历 procurement_plan 中的 PENDING Slot，检查对应字段是否已存在于 trip_data 中。
    如果存在，生成状态更新记录。

    支持 Schema Normalization：即使 Planner 生成的字段名与映射表不完全一致，
    也能通过模糊匹配找到正确的数据源。

    Returns:
        需要通过 reducer 更新的 Slot 列表
    """
    procurement_plan = state.get("procurement_plan", [])
    trip_data = state.get("trip_data", {})
    updates = []

    for slot in procurement_plan:
        if slot.get("status") != "PENDING":
            continue

        field_name = slot.get("field_name", "")
        key, extractor = None, None

        # 方式 1: 精确匹配
        if field_name in FIELD_TO_TRIP_DATA:
            key, extractor = FIELD_TO_TRIP_DATA[field_name]

        # 方式 2: 模糊匹配（Schema Normalization）
        if not key:
            normalized = _normalize_field_name(field_name)
            if normalized and normalized in FIELD_TO_TRIP_DATA:
                key, extractor = FIELD_TO_TRIP_DATA[normalized]
                debug_print(f"[Supervisor] 模糊匹配: {field_name} → {normalized}")

        # 执行数据提取
        if key and extractor:
            data = trip_data.get(key)
            if data:
                try:
                    value = extractor(data)
                    if value:
                        updates.append({
                            "id": slot["id"],
                            "status": "FILLED",
                            "value": str(value)[:500],  # 截断避免过长
                        })
                        debug_print(f"[Supervisor] 同步: {slot['id']} FILLED (from trip_data.{key})")
                except Exception as e:
                    debug_print(f"[Supervisor] 同步失败 {slot['id']}: {e}")

    return updates


# ==================== 依赖解析函数 ====================


def _find_runnable_slot(state: GraphState) -> dict | None:
    """寻找可执行任务：找到第一个 PENDING 且依赖全部满足的 Slot

    规则：
    1. 状态必须是 PENDING
    2. dependencies 列表中的所有 Slot ID 都必须是 FILLED 状态

    Returns:
        下一个可执行的 Slot，或 None（全部完成/死锁）
    """
    procurement_plan = state.get("procurement_plan", [])
    id_to_slot = {s["id"]: s for s in procurement_plan}

    for slot in procurement_plan:
        if slot.get("status") != "PENDING":
            continue

        # 检查所有依赖是否满足
        deps = slot.get("dependencies", [])
        all_deps_filled = all(
            id_to_slot.get(dep_id, {}).get("status") == "FILLED"
            for dep_id in deps
        )

        if all_deps_filled:
            return slot

    return None


def _check_completion(state: GraphState) -> tuple[bool, bool, str]:
    """检查是否完成或死锁

    Returns:
        (is_complete, is_deadlock, reason)
    """
    procurement_plan = state.get("procurement_plan", [])

    if not procurement_plan:
        return True, False, "采购计划为空"

    statuses = [s.get("status", "PENDING") for s in procurement_plan]
    pending = statuses.count("PENDING")
    dispatched = statuses.count("DISPATCHED")
    filled = statuses.count("FILLED")
    failed = statuses.count("FAILED")

    # 全部完成（没有 PENDING 和 DISPATCHED）
    if pending == 0 and dispatched == 0:
        return True, False, f"采购完成: {filled} FILLED, {failed} FAILED"

    # 死锁检测：有 PENDING 但找不到可执行的
    # 注意：这里需要先应用同步更新再检查
    runnable = _find_runnable_slot(state)
    if runnable is None and pending > 0 and dispatched == 0:
        return False, True, f"死锁: {pending} 个 Slot 依赖未满足"

    return False, False, ""


# ==================== 上下文注水函数 ====================


def _hydrate_instruction(slot: dict, state: GraphState) -> str:
    """上下文注水：将依赖数据注入指令

    从依赖 Slot 的 value 中提取实体信息，构建包含具体实体名的指令。
    这是解决"空容器"问题的关键。

    包含空值防御机制：如果上游数据无效，返回 ABORT 指令让 Agent 快速失败。

    Args:
        slot: 当前要执行的 Slot
        state: 图状态

    Returns:
        注水后的指令字符串
    """
    procurement_plan = state.get("procurement_plan", [])
    id_to_slot = {s["id"]: s for s in procurement_plan}

    base_desc = slot.get("description", "")
    deps = slot.get("dependencies", [])
    source_agent = slot.get("source_agent", "")

    # 收集依赖的值
    context_parts = []
    entity_values = {}  # 用于特定模板

    for dep_id in deps:
        dep_slot = id_to_slot.get(dep_id)
        if dep_slot and dep_slot.get("value"):
            field_name = dep_slot.get("field_name", "unknown")
            value = dep_slot["value"]
            context_parts.append(f"{field_name}='{value}'")
            entity_values[field_name] = value

    # === 空值防御：检测无效实体 ===
    INVALID_VALUES = frozenset([
        "none", "null", "未知", "unknown", "未知酒店", "未知球场", "",
        "n/a", "na", "无", "暂无", "待定", "tbd", "未填写",
    ])

    if source_agent == "search_agent" and entity_values:
        # Search Agent 依赖外部实体，必须验证有效性
        for field, value in entity_values.items():
            value_str = str(value).lower().strip() if value else ""
            # 检查是否是无效值或包含系统提示语
            is_invalid = (
                value_str in INVALID_VALUES or
                value_str.startswith("[") or  # 系统消息如 "[hotel_agent] 数据已获取..."
                "数据已获取" in value_str or
                "无法提取" in value_str
            )
            if is_invalid:
                debug_print(f"[Supervisor] 空值防御: {field}='{value}' 无效，中止 search_agent")
                return f"[ABORT] 依赖数据 '{field}' 无效（值: {value}），无法执行搜索。请直接返回 FAILURE。"

    # 根据目标 Agent 构建专用模板
    if source_agent == "search_agent" and entity_values:
        # Search Agent 专用模板 - 使用具体实体名
        if "hotel_name" in entity_values:
            return f"搜索酒店 '{entity_values['hotel_name']}' 的评价、口碑和用户反馈"
        elif "course_name" in entity_values:
            return f"搜索球场 '{entity_values['course_name']}' 的攻略、难度评价和打球建议"
        elif context_parts:
            entity_info = ", ".join(context_parts)
            return f"搜索 {entity_info} 的相关信息: {base_desc}"

    elif source_agent == "weather_agent" and entity_values:
        # Weather Agent 专用模板
        location = entity_values.get("location") or entity_values.get("destination")
        if location:
            return f"查询 '{location}' 的天气预报"

    elif context_parts:
        # 通用模板 - 附加上下文
        return f"{base_desc} (上下文: {', '.join(context_parts)})"

    return base_desc


# ==================== Worker 结果处理 ====================


def _handle_worker_result(state: GraphState) -> list[dict]:
    """处理 Worker 返回结果，更新 DISPATCHED Slot 的状态

    检查最后一条消息，判断对应的 Worker 是否成功完成任务。
    成功则标记为 FILLED，失败则标记为 FAILED。

    Returns:
        需要通过 reducer 更新的 Slot 列表
    """
    procurement_plan = state.get("procurement_plan", [])
    trip_data = state.get("trip_data", {})
    messages = state.get("messages", [])

    if not messages:
        return []

    last_msg = messages[-1]
    last_msg_name = getattr(last_msg, "name", None)
    last_msg_content = getattr(last_msg, "content", "") or ""

    updates = []

    for slot in procurement_plan:
        if slot.get("status") != "DISPATCHED":
            continue

        # 检查是否是这个 Agent 的返回
        agent_name = slot.get("source_agent", "")
        if agent_name != last_msg_name:
            continue

        # 检查是否失败
        failure_keywords = ["FAILURE", "MISSING_CAPABILITY", "失败", "无法获取", "Error"]
        is_failure = any(kw in last_msg_content for kw in failure_keywords)

        if is_failure:
            updates.append({
                "id": slot["id"],
                "status": "FAILED",
                "value": f"失败: {last_msg_content[:100]}",
            })
            debug_print(f"[Supervisor] Worker 失败: {slot['id']} -> FAILED")
        else:
            # 成功 - 使用增强的数据提取函数
            real_value = _extract_real_value(trip_data, slot)

            if real_value:
                updates.append({
                    "id": slot["id"],
                    "status": "FILLED",
                    "value": real_value,
                })
                # 截断显示用于调试
                display_value = real_value[:50] + "..." if len(real_value) > 50 else real_value
                debug_print(f"[Supervisor] Worker 成功: {slot['id']} -> FILLED (value: {display_value})")
            else:
                # 无法提取真实值，仍标记为 FILLED 但记录警告
                # 注意：不再使用 "已完成" 占位符，而是给出明确提示
                fallback_msg = f"[{slot.get('source_agent')}] 数据已获取，但无法提取 {slot.get('field_name')}"
                updates.append({
                    "id": slot["id"],
                    "status": "FILLED",
                    "value": fallback_msg,
                })
                debug_print(f"[Supervisor] Worker 成功但值提取失败: {slot['id']} - {fallback_msg}")

    return updates


# ==================== 辅助函数 ====================


def _get_analysis_strategy(state: GraphState) -> AnalysisStrategy:
    """从 refined_plan 中提取分析策略"""
    refined_plan = state.get("refined_plan", "{}")
    try:
        plan = json.loads(refined_plan)
        return plan.get("analysis_strategy", "GENERAL")
    except (json.JSONDecodeError, TypeError):
        return "GENERAL"


def _format_slot_status(procurement_plan: list[dict]) -> str:
    """格式化 Slot 状态用于调试输出"""
    if not procurement_plan:
        return "空"

    lines = []
    for slot in procurement_plan:
        status = slot.get("status", "?")
        deps = slot.get("dependencies", [])
        dep_str = f" <- {deps}" if deps else ""
        lines.append(f"  [{status}] {slot.get('id')}: {slot.get('field_name')}{dep_str}")

    return "\n".join(lines)


# ==================== 主节点函数 ====================


def supervisor_node(state: GraphState, llm: BaseChatModel) -> dict:
    """Supervisor 节点 - DAG 执行引擎

    执行流程：
    1. 处理上一个 Worker 的返回结果
    2. 数据同步（检查 trip_data）
    3. 完成/死锁检查
    4. 寻找可执行任务（依赖解析）
    5. 上下文注水
    6. 调度
    """

    iteration = state.get("iteration_count", 0)
    procurement_plan = state.get("procurement_plan", [])

    # 节点入口标识
    print_node_enter("supervisor", iteration=iteration)

    # 入口处展示当前食谱状态
    print_recipe_status(procurement_plan, "当前食谱状态")

    # === 安全阈值 ===
    if iteration >= 10:
        print_completion("达到最大迭代次数，强制路由到 analyst", is_success=False)
        print_routing("supervisor", "analyst", "最大迭代")
        return {
            "next_step": "analyst",
            "supervisor_instructions": "已达最大迭代次数，请总结现有信息回复用户",
            "analysis_strategy": "GENERAL",
            "iteration_count": 1,
            "messages": [AIMessage(
                content="[Supervisor] 达到最大迭代次数，强制路由到 analyst",
                name="supervisor"
            )],
        }

    # === 1. 处理 Worker 返回结果 ===
    worker_updates = _handle_worker_result(state)

    # === 2. 数据同步 ===
    sync_updates = _sync_with_trip_data(state)

    # 合并所有更新
    all_updates = worker_updates + sync_updates

    # 应用更新后重新检查状态（模拟更新）
    updated_plan = procurement_plan  # 默认值
    if all_updates:
        # 创建更新后的 procurement_plan 视图
        updated_plan = [slot.copy() for slot in procurement_plan]
        id_to_idx = {slot["id"]: i for i, slot in enumerate(updated_plan)}
        for update in all_updates:
            slot_id = update.get("id")
            if slot_id and slot_id in id_to_idx:
                idx = id_to_idx[slot_id]
                updated_plan[idx] = {**updated_plan[idx], **update}

        # 使用更新后的视图进行后续检查
        temp_state = {**state, "procurement_plan": updated_plan}

        # 展示 Worker 结果
        if worker_updates:
            print_section("Worker 结果处理", "📦")
            for upd in worker_updates:
                print_worker_result(upd["id"], upd["status"], upd.get("value"))

        # 展示数据同步
        if sync_updates:
            print_section("数据同步", "🔄")
            for upd in sync_updates:
                slot = next((s for s in procurement_plan if s["id"] == upd["id"]), {})
                print_data_sync(upd["id"], slot.get("field_name", "?"), "trip_data")
    else:
        temp_state = state

    # === 3. 完成/死锁检查 ===
    is_complete, is_deadlock, reason = _check_completion(temp_state)

    analysis_strategy = _get_analysis_strategy(state)

    if is_complete:
        print_recipe_status(updated_plan, "最终状态", show_summary=True)
        print_completion(reason, is_success=True)
        print_routing("supervisor", "analyst", "采集完成")
        return {
            "next_step": "analyst",
            "supervisor_instructions": f"数据采集完成: {reason}",
            "analysis_strategy": analysis_strategy,
            "iteration_count": 1,
            "procurement_plan": all_updates,
            "messages": [AIMessage(
                content=f"[Supervisor] {reason}，路由到 analyst",
                name="supervisor"
            )],
        }

    if is_deadlock:
        print_recipe_status(updated_plan, "死锁状态", show_summary=True)
        print_completion(f"死锁: {reason}", is_success=False)
        print_routing("supervisor", "analyst", "死锁")
        return {
            "next_step": "analyst",
            "supervisor_instructions": f"检测到死锁: {reason}，请基于现有数据回答",
            "analysis_strategy": "GENERAL",
            "iteration_count": 1,
            "procurement_plan": all_updates,
            "messages": [AIMessage(
                content=f"[Supervisor] 死锁警告: {reason}",
                name="supervisor"
            )],
        }

    # === 4. 寻找可执行任务 ===
    runnable = _find_runnable_slot(temp_state)

    if not runnable:
        # 可能还有 DISPATCHED 的任务在执行中，等待
        print_completion("无可执行任务，等待中的任务可能未正确返回", is_success=False)
        print_routing("supervisor", "analyst", "无可执行")
        return {
            "next_step": "analyst",
            "supervisor_instructions": "等待中的任务可能未正确返回，请综合现有数据回答",
            "analysis_strategy": analysis_strategy,
            "iteration_count": 1,
            "procurement_plan": all_updates,
            "messages": [AIMessage(
                content="[Supervisor] 无可执行任务",
                name="supervisor"
            )],
        }

    # === 5. 上下文注水 ===
    instruction = _hydrate_instruction(runnable, temp_state)

    # === 6. 调度 ===
    dispatch_update = {
        "id": runnable["id"],
        "status": "DISPATCHED",
    }

    target_agent = runnable.get("source_agent", "analyst")

    # 打印调度信息
    print_dispatch(target_agent, runnable, instruction)

    # 展示调度后的食谱状态（模拟 DISPATCHED 更新）
    dispatch_preview = [slot.copy() for slot in updated_plan]
    for slot in dispatch_preview:
        if slot["id"] == runnable["id"]:
            slot["status"] = "DISPATCHED"
            break
    print_recipe_status(dispatch_preview, "调度后状态")

    # 路由决策
    print_routing("supervisor", target_agent, f"执行 {runnable.get('field_name')}")

    return {
        "next_step": target_agent,
        "supervisor_instructions": instruction,
        "analysis_strategy": analysis_strategy,
        "iteration_count": 1,
        "procurement_plan": all_updates + [dispatch_update],
        "messages": [AIMessage(
            content=f"[Supervisor] 调度 {target_agent}: {runnable.get('field_name')}\n  指令: {instruction}",
            name="supervisor"
        )],
    }
