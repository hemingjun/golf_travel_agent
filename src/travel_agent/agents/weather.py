"""Weather Agent - 天气查询 (Gemini 上下文感知修复版)"""

import json
import re
from datetime import date, datetime, timedelta

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from ..graph.state import GraphState
from ..tools.weather import get_location_weather
from ..debug import debug_print, print_node_enter, print_routing, print_trip_data_update


def _parse_planner_params(state: GraphState) -> dict:
    """从 Planner 的 refined_plan 中提取参数"""
    refined_plan = state.get("refined_plan", "{}")
    try:
        plan = json.loads(refined_plan)
        return plan.get("resolved_params", {})
    except (json.JSONDecodeError, TypeError):
        return {}


def _extract_params_with_llm(state: GraphState, llm) -> dict:
    """【核心修复】从上下文历史中提取参数 (Context-Aware Extraction)"""
    
    # 1. 收集上下文：不再只看 Planner，而是看最近的对话历史
    # 这让 Agent 能看到 Itinerary Agent 刚刚查到的 "Los Cabos"
    context_parts = []
    
    # A. Planner 的原始任务 (作为背景)
    refined_plan_str = state.get("refined_plan", "{}")
    try:
        plan_json = json.loads(refined_plan_str)
        task_seq = plan_json.get("task_sequence", [])
        if isinstance(task_seq, list):
            context_parts.extend(task_seq)
    except:
        pass
        
    # B. 【关键】最近的 3 条历史消息 (包含 Supervisor 的指令 和 Itinerary 的结果)
    messages = state.get("messages", [])
    recent_messages = messages[-3:] if messages else []
    
    for msg in recent_messages:
        if isinstance(msg, (AIMessage, HumanMessage, SystemMessage, ToolMessage)):
            # 加上前缀以便 LLM 区分是谁说的
            role = msg.type
            content = str(msg.content)
            context_parts.append(f"[{role}]: {content}")
        
    full_context = "\n".join(context_parts)
    if not full_context.strip():
        return {}

    # 获取当前日期用于推算
    current_date = state.get("current_date", datetime.now().strftime("%Y-%m-%d"))

    # 2. 构建 Prompt - 明确区分用户查询日期和行程日期
    prompt = f"""你是一个智能参数提取助手。
当前任务是查询天气，请根据对话历史提取【地点】和【用户想查询的日期】。

**当前日期**: {current_date}

**提取规则**:
1. **location**: 提取地点英文名（优先使用 Supervisor 指令中的地点，或 Itinerary 中发现的具体地点）
2. **dates**: 只提取**用户明确想查询的日期**，转换为 "YYYY-MM-DD" 格式
   - "这两天" → 从 {current_date} 开始往后 2 天
   - "明天" → {current_date} 的下一天
   - "下周" → 计算下周的日期
   - **重要**: 不要提取行程中的日期，除非用户明确说"行程期间"或"打球那天"

上下文内容：
---
{full_context}
---

请仅返回 JSON 格式：
{{"location": "Los Cabos", "dates": ["2026-01-20", "2026-01-21"]}}
"""

    try:
        # 使用 HumanMessage 触发 Gemini
        response = llm.invoke([HumanMessage(content=prompt)])
        content = response.content.strip()
        if "```json" in content:
            content = content.replace("```json", "").replace("```", "")
        return json.loads(content)
    except Exception as e:
        print(f"[Weather Agent] LLM 提取失败: {e}")
        return {}


def _infer_location_from_trip(trip_data: dict, params: dict) -> str | None:
    """从行程数据推断位置 (辅助兜底)"""
    location_type = params.get("location_type", "")

    # 如果指定了球场，尝试找球场
    if location_type == "first_golf_course" or location_type == "golf_course":
        bookings = trip_data.get("golf_bookings", [])
        if bookings: return bookings[0].get("球场地址") or bookings[0].get("球场名称")
        # 尝试从 events 里找 (兼容 Itinerary Agent 的返回格式)
        events = trip_data.get("events", [])
        for evt in events:
            if "球场" in str(evt) or "挥杆" in str(evt):
                return str(evt) # 简单返回事件描述，靠 Tool 去模糊匹配

    # 默认兜底
    hotel_bookings = trip_data.get("hotel_bookings", [])
    if hotel_bookings:
        return hotel_bookings[0].get("酒店地址") or hotel_bookings[0].get("酒店名称")

    return None


def _normalize_date(date_str: str) -> str:
    """标准化日期为 YYYY-MM-DD"""
    if not date_str:
        return datetime.now().strftime("%Y-%m-%d")
    clean = date_str.replace("年", "-").replace("月", "-").replace("日", "")
    match = re.search(r"(\d{4}-\d{1,2}-\d{1,2})", clean)
    if match: return match.group(1)
    return clean


def _get_specific_weather(state: GraphState, params: dict) -> dict:
    """单点查询逻辑"""
    trip_data = state.get("trip_data", {})
    
    # 1. 确定地点
    location = params.get("location") or params.get("city") or params.get("地点")
    if not location:
        location = _infer_location_from_trip(trip_data, params)

    if not location:
        return {
            "messages": [AIMessage(content="[Weather Agent] 无法确定查询位置，请指定城市名称。", name="weather_agent")]
        }

    # 2. 确定日期 - 优先使用用户查询日期
    raw_dates = (
        params.get("time_range") or      # 优先：用户明确查询的时间范围
        params.get("query_dates") or     # 备选：查询日期
        params.get("dates") or           # 通用日期
        params.get("target_date") or
        params.get("date") or
        params.get("日期")
    )
    if raw_dates is None:
        raw_dates = [state.get("current_date", datetime.now().strftime("%Y-%m-%d"))]
    elif isinstance(raw_dates, str):
        raw_dates = [raw_dates]
        
    # 3. 执行查询
    weather_reports = []
    messages = []
    
    for raw_date in raw_dates:
        query_date = _normalize_date(str(raw_date))
        weather = get_location_weather(location, query_date)
        
        if weather and "error" not in weather and weather is not None:
            # 优化报告格式，包含地点
            report_item = {
                "date": query_date,
                "location": location,
                "desc": weather.get("weather", ""),
                "temp": f"{weather.get('temp_min')}-{weather.get('temp_max')}°C",
                "rain": f"{weather.get('rain_probability')}%"
            }
            weather_reports.append(report_item)
            messages.append(f"- {query_date} @ {location}: {weather.get('weather')}, {weather.get('temp_min')}-{weather.get('temp_max')}°C")
        else:
            messages.append(f"- {query_date} @ {location}: 暂无数据")

    summary = f"[Weather Agent] 查询结果:\n" + "\n".join(messages)

    # 展示数据更新
    print_trip_data_update("weather_report", weather_reports)
    print_routing("weather_agent", "supervisor", f"查询 {location} 天气完成")

    return {
        "trip_data": {"weather_report": weather_reports},
        "messages": [AIMessage(content=summary, name="weather_agent")]
    }


def _get_trip_weather(state: GraphState) -> dict:
    """兜底"""
    print_routing("weather_agent", "supervisor", "缺少参数，无法查询")
    return {
        "messages": [AIMessage(content="[Weather Agent] 缺少明确参数且无行程数据，无法查询。", name="weather_agent")]
    }


def weather_agent(state: GraphState, llm=None) -> dict:
    """主入口"""
    # 节点入口标识
    print_node_enter("weather_agent")

    params = _parse_planner_params(state)
    
    # --- 智能参数补全 ---
    # 只要 params 里缺 location 或者缺 dates，就启动 LLM 去看历史记录
    # 这样就能捕捉到 Itinerary Agent 刚刚发现的新地点
    if not params.get("location") or not params.get("dates"):
        if llm:
            debug_print("--> [Weather Agent] 参数不全，正在扫描上下文历史...")
            fallback_params = _extract_params_with_llm(state, llm)
            if fallback_params:
                params.update(fallback_params)
                debug_print(f"--> [Weather Agent] 从历史中提取到参数: {params}")

    # 路由
    if params.get("location") or params.get("dates"):
        return _get_specific_weather(state, params)
    else:
        return _get_trip_weather(state)