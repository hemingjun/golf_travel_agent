"""Weather Agent - 天气查询 (Gemini 适配修复版)"""

import json
import re
from datetime import date, datetime, timedelta

# ⚠️ 关键修改：导入 HumanMessage
from langchain_core.messages import AIMessage, HumanMessage 

from ..graph.state import GraphState
from ..tools.weather import get_location_weather


def _parse_planner_params(state: GraphState) -> dict:
    """从 Planner 的 refined_plan 中提取参数"""
    refined_plan = state.get("refined_plan", "{}")
    try:
        plan = json.loads(refined_plan)
        return plan.get("resolved_params", {})
    except (json.JSONDecodeError, TypeError):
        return {}


def _extract_params_with_llm(state: GraphState, llm) -> dict:
    """【核心修复】从自然语言指令中提取参数"""
    
    # 1. 收集上下文
    context_parts = []
    
    refined_plan_str = state.get("refined_plan", "{}")
    try:
        plan_json = json.loads(refined_plan_str)
        task_seq = plan_json.get("task_sequence", [])
        if isinstance(task_seq, list):
            context_parts.extend(task_seq)
        elif isinstance(task_seq, str):
            context_parts.append(task_seq)
    except:
        pass
        
    instructions = state.get("supervisor_instructions", "")
    if instructions:
        context_parts.append(instructions)
        
    full_context = "\n".join(context_parts)
    if not full_context.strip():
        return {}

    # 2. 构建 Prompt
    prompt = f"""你是一个智能参数提取助手。
上游系统生成的 JSON 参数丢失了，但自然语言指令中包含了正确信息。
请阅读以下指令，提取【地点】和【日期】。

指令内容：
---
{full_context}
---

提取要求：
1. **location**: 提取城市或地点英文名（如 "Vancouver"）。
2. **dates**: 提取所有提到的日期，转换为 "YYYY-MM-DD" 格式的列表。

请仅返回 JSON 格式，不要包含 Markdown 标记。例如：
{{"location": "Vancouver", "dates": ["2026-01-18"]}}
"""

    try:
        # ⚠️ 关键修复：这里必须使用 HumanMessage，不能用 SystemMessage
        # Gemini API 要求对话必须包含至少一条 User 消息
        response = llm.invoke([HumanMessage(content=prompt)])
        
        content = response.content.strip()
        if "```json" in content:
            content = content.replace("```json", "").replace("```", "")
        return json.loads(content)
    except Exception as e:
        print(f"[Weather Agent] LLM 提取失败: {e}")
        return {}


def _infer_location_from_trip(trip_data: dict, params: dict) -> str | None:
    """从行程数据推断位置"""
    location_type = params.get("location_type", "")

    if location_type == "first_golf_course":
        bookings = trip_data.get("golf_bookings", [])
        if bookings: return bookings[0].get("球场地址") or bookings[0].get("球场名称")

    if location_type == "hotel":
        bookings = trip_data.get("hotel_bookings", [])
        if bookings: return bookings[0].get("酒店地址") or bookings[0].get("酒店名称")

    hotel_bookings = trip_data.get("hotel_bookings", [])
    if hotel_bookings:
        return hotel_bookings[0].get("酒店地址") or hotel_bookings[0].get("酒店名称")

    golf_bookings = trip_data.get("golf_bookings", [])
    if golf_bookings:
        return golf_bookings[0].get("球场地址") or golf_bookings[0].get("球场名称")

    return None


def _normalize_date(date_str: str) -> str:
    """标准化日期为 YYYY-MM-DD"""
    if not date_str:
        return datetime.now().strftime("%Y-%m-%d")
    
    clean = date_str.replace("年", "-").replace("月", "-").replace("日", "")
    match = re.search(r"(\d{4}-\d{1,2}-\d{1,2})", clean)
    if match:
        return match.group(1)
    return clean


def _get_specific_weather(state: GraphState, params: dict) -> dict:
    """单点查询逻辑"""
    trip_data = state.get("trip_data", {})
    
    location = params.get("location") or params.get("city") or params.get("地点")
    if not location:
        location = _infer_location_from_trip(trip_data, params)

    if not location:
        return {
            "messages": [AIMessage(content="[Weather Agent] 无法确定查询位置，请指定城市名称。", name="weather_agent")]
        }

    raw_dates = params.get("dates") or params.get("target_date") or params.get("date") or params.get("日期")
    
    if raw_dates is None:
        raw_dates = [state.get("current_date", datetime.now().strftime("%Y-%m-%d"))]
    elif isinstance(raw_dates, str):
        raw_dates = [raw_dates]
        
    weather_reports = []
    messages = []
    
    for raw_date in raw_dates:
        query_date = _normalize_date(str(raw_date))
        weather = get_location_weather(location, query_date)
        
        if weather and "error" not in weather and weather is not None:
            weather_reports.append({
                "date": query_date,
                "location": location,
                "desc": weather.get("weather", ""),
                "temp": f"{weather.get('temp_min')}-{weather.get('temp_max')}°C",
                "rain": f"{weather.get('rain_probability')}%"
            })
            messages.append(f"- {query_date}: {weather.get('weather')}, {weather.get('temp_min')}-{weather.get('temp_max')}°C (降水 {weather.get('rain_probability')}%)")
        else:
            messages.append(f"- {query_date}: 暂无数据")

    summary = f"[Weather Agent] {location} 天气预报:\n" + "\n".join(messages)
    
    return {
        "trip_data": {"weather_report": weather_reports},
        "messages": [AIMessage(content=summary, name="weather_agent")]
    }


def _get_trip_weather(state: GraphState) -> dict:
    """兜底：无法解析参数时"""
    return {
        "messages": [AIMessage(content="[Weather Agent] 缺少明确参数且无行程数据，无法查询。", name="weather_agent")]
    }


def weather_agent(state: GraphState, llm=None) -> dict:
    """主入口"""
    params = _parse_planner_params(state)
    
    # 智能兜底逻辑
    is_empty_params = not params or (not params.get("location") and not params.get("dates"))
    
    if is_empty_params and llm:
        print("--> [Weather Agent] JSON 参数缺失，正在使用 Flash 模型阅读指令...")
        fallback_params = _extract_params_with_llm(state, llm)
        if fallback_params:
            params.update(fallback_params)
            print(f"--> [Weather Agent] 成功提取参数: {params}")

    # 路由逻辑
    has_specific = any(k in params for k in ["location", "city", "dates", "date", "target_date"])
    
    if has_specific:
        return _get_specific_weather(state, params)
    else:
        return _get_trip_weather(state)