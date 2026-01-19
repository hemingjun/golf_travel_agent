"""Search Agent - 情报官 (Intel Officer)

负责互联网搜索，对结果进行去噪、时效性判断和来源引用。
支持动态上下文替换，解决 Planner 占位符问题。
"""

import re
import json
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.language_models import BaseChatModel

from ..graph.state import GraphState
from ..debug import debug_print, print_node_enter, print_routing, print_trip_data_update, print_kv, print_section


# 常见占位符模式
PLACEHOLDER_PATTERNS = [
    r"\{[\w_]+\}",           # 大括号格式: {hotel_name}, {golf_course} 等
    r"hotel\s*name",
    r"the\s+hotel",
    r"place\s*name",
    r"golf\s*course\s*name",
    r"the\s+course",
    r"restaurant\s*name",
    r"the\s+restaurant",
    r"location\s*name",
    r"entity\s*name",
]


def _has_placeholder(query: str) -> bool:
    """检测查询是否包含占位符"""
    query_lower = query.lower()
    for pattern in PLACEHOLDER_PATTERNS:
        if re.search(pattern, query_lower, re.IGNORECASE):
            return True
    return False


def _extract_entities_from_context(state: GraphState) -> dict:
    """从 trip_data 中提取可用的实体名称

    Returns:
        {
            "hotel": "酒店名称",
            "golf_course": "球场名称",
            "location": "目的地",
            ...
        }
    """
    entities = {}
    trip_data = state.get("trip_data", {})

    # 提取酒店名称
    hotel_bookings = trip_data.get("hotel_bookings", [])
    if hotel_bookings:
        for booking in hotel_bookings:
            hotel_name = booking.get("hotel_name") or booking.get("hotel_name_en")
            if hotel_name and hotel_name != "未知酒店":
                entities["hotel"] = hotel_name
                break

    # 提取球场名称
    golf_bookings = trip_data.get("golf_bookings", [])
    if golf_bookings:
        for booking in golf_bookings:
            course_name = booking.get("course_name") or booking.get("course_name_en")
            if course_name:
                entities["golf_course"] = course_name
                break

    # 从行程信息提取目的地
    trip_info = trip_data.get("trip_info", {})
    if trip_info:
        location = trip_info.get("location") or trip_info.get("destination")
        if location:
            entities["location"] = location

    # 从 events 中提取实体（如果上面没找到）
    events = trip_data.get("events", [])
    for event in events:
        event_type = event.get("type", "").lower()
        event_name = event.get("name") or event.get("description", "")

        if "hotel" not in entities and "酒店" in event_type:
            entities["hotel"] = event_name
        if "golf_course" not in entities and ("球场" in event_type or "golf" in event_type):
            entities["golf_course"] = event_name

    return entities


def _refine_query_with_context(query: str, state: GraphState, llm: BaseChatModel) -> str:
    """使用上下文替换查询中的占位符

    策略：
    1. 先尝试规则替换（从 trip_data 提取实体）
    2. 如果规则替换失败，使用 LLM 进行智能替换
    """
    # 1. 提取可用实体
    entities = _extract_entities_from_context(state)
    debug_print(f"[Search Agent] 可用实体: {entities}")

    if not entities:
        debug_print("[Search Agent] 无可用实体进行替换")
        return query

    # 2. 规则替换
    refined_query = query
    query_lower = query.lower()

    # 酒店名称替换
    if "hotel" in entities:
        hotel_name = entities["hotel"]
        for pattern in [r"hotel\s*name", r"the\s+hotel"]:
            if re.search(pattern, query_lower, re.IGNORECASE):
                refined_query = re.sub(pattern, hotel_name, refined_query, flags=re.IGNORECASE)
                debug_print(f"[Search Agent] 替换酒店名称: {hotel_name}")

    # 球场名称替换
    if "golf_course" in entities:
        course_name = entities["golf_course"]
        for pattern in [r"golf\s*course\s*name", r"the\s+course"]:
            if re.search(pattern, query_lower, re.IGNORECASE):
                refined_query = re.sub(pattern, course_name, refined_query, flags=re.IGNORECASE)
                debug_print(f"[Search Agent] 替换球场名称: {course_name}")

    # 地点名称替换
    if "location" in entities:
        location = entities["location"]
        for pattern in [r"place\s*name", r"location\s*name"]:
            if re.search(pattern, query_lower, re.IGNORECASE):
                refined_query = re.sub(pattern, location, refined_query, flags=re.IGNORECASE)
                debug_print(f"[Search Agent] 替换地点: {location}")

    # 大括号格式占位符替换 (如 {hotel_name}, {golf_course})
    if "hotel" in entities:
        hotel_name = entities["hotel"]
        if re.search(r"\{hotel_name\}", refined_query, re.IGNORECASE):
            refined_query = re.sub(r"\{hotel_name\}", hotel_name, refined_query, flags=re.IGNORECASE)
            debug_print(f"[Search Agent] 替换 {{hotel_name}}: {hotel_name}")

    if "golf_course" in entities:
        course_name = entities["golf_course"]
        for pattern in [r"\{golf_course\}", r"\{course_name\}"]:
            if re.search(pattern, refined_query, re.IGNORECASE):
                refined_query = re.sub(pattern, course_name, refined_query, flags=re.IGNORECASE)
                debug_print(f"[Search Agent] 替换球场占位符: {course_name}")

    if "location" in entities:
        location = entities["location"]
        for pattern in [r"\{location\}", r"\{place_name\}"]:
            if re.search(pattern, refined_query, re.IGNORECASE):
                refined_query = re.sub(pattern, location, refined_query, flags=re.IGNORECASE)
                debug_print(f"[Search Agent] 替换地点占位符: {location}")

    # 3. 如果规则替换后仍有占位符，尝试 LLM 替换
    if _has_placeholder(refined_query) and llm:
        debug_print("[Search Agent] 规则替换不完全，尝试 LLM 优化")
        try:
            context_str = json.dumps(entities, ensure_ascii=False)
            refine_prompt = f"""请将以下搜索查询中的通用占位符替换为具体的实体名称。

可用实体信息：
{context_str}

原始查询：{refined_query}

请直接输出替换后的搜索查询，不要解释："""

            response = llm.invoke([HumanMessage(content=refine_prompt)])
            llm_refined = response.content.strip()
            if llm_refined and len(llm_refined) < len(refined_query) * 3:  # 防止 LLM 输出过长
                refined_query = llm_refined
                debug_print(f"[Search Agent] LLM 优化后: {refined_query}")
        except Exception as e:
            debug_print(f"[Search Agent] LLM 优化失败: {e}")

    return refined_query


SEARCH_PROMPT = """你是高尔夫旅行团队的**情报官 (Intel Officer)**。
你的任务是利用 Google Search 查询数据库中没有的实时公开信息。

## 执行准则

### 1. 精准去噪
- 只提取与任务紧密相关的**事实性信息**
- 忽略 SEO 废话、广告内容、无关推广
- 优先引用权威来源（官方网站、知名媒体、专业评测）

### 2. 时效优先
- 汇率、天气、新闻必须基于**最新**搜索结果
- 明确标注信息的时效性（如"截至2026年1月"）
- 过期信息需特别注明

### 3. 来源引用
- 关键信息需注明来源
- 格式：「信息内容 (来源: xxx)」

### 4. 拒绝幻觉
- 搜不到就直接说"未找到相关信息"
- **严禁编造**任何数据或事实

## 输出格式
请用简洁的结构化格式呈现搜索结果：

**搜索主题**: xxx
**关键发现**:
1. xxx (来源: xxx)
2. xxx (来源: xxx)
**时效说明**: xxx

---

## 当前搜索任务
{search_query}
"""


def _extract_search_query(state: GraphState) -> tuple[str, str]:
    """提取搜索查询 - 优先使用明确指令

    优先级：
    1. refined_plan 中的 search_agent 任务指令
    2. supervisor_instructions
    3. 用户最新消息 (回退)

    Returns:
        (search_query, source) - 搜索内容和来源标识
    """
    # 优先级 1: 从 refined_plan 中提取搜索任务
    refined_plan_str = state.get("refined_plan", "")
    if refined_plan_str:
        try:
            plan = json.loads(refined_plan_str)
            task_sequence = plan.get("task_sequence", [])

            # 查找 search_agent 相关任务
            for task in task_sequence:
                task_lower = task.lower()
                if "search" in task_lower or "搜索" in task:
                    # 提取任务描述作为搜索内容
                    # 格式: "[search_agent] Search for 'xxx'" 或 "搜索 xxx"
                    search_content = task
                    # 清理前缀
                    for prefix in ["[search_agent]", "[Search]", "search_agent:", "Search:"]:
                        if prefix.lower() in search_content.lower():
                            idx = search_content.lower().find(prefix.lower())
                            search_content = search_content[idx + len(prefix):].strip()
                            break

                    if search_content:
                        return search_content, "refined_plan"
        except (json.JSONDecodeError, AttributeError):
            pass

    # 优先级 2: supervisor_instructions
    supervisor_instructions = state.get("supervisor_instructions", "")
    if supervisor_instructions and len(supervisor_instructions) > 5:
        return supervisor_instructions, "supervisor"

    # 优先级 3: 用户最新消息 (回退)
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            return msg.content, "user_message"

    return "未知搜索任务", "fallback"


def search_agent(state: GraphState, llm: BaseChatModel) -> dict:
    """Search Agent - 情报官

    执行互联网搜索，对结果进行去噪和结构化整理。
    支持动态上下文替换，自动将占位符替换为实际实体名称。

    Args:
        state: 图状态
        llm: LLM 实例（将绑定 Google Search 工具）

    Returns:
        包含 trip_data["search_findings"] 和 messages 的字典
    """

    # 节点入口标识
    print_node_enter("search_agent")

    # 1. 提取搜索查询 (优先明确指令)
    raw_query, query_source = _extract_search_query(state)

    print_section("搜索任务", "🔍")
    print_kv("来源", query_source)
    print_kv("原始查询", raw_query[:80] + "..." if len(raw_query) > 80 else raw_query)

    # 2. 动态上下文替换（解决占位符问题）
    if _has_placeholder(raw_query):
        debug_print("[Search Agent] 检测到占位符，执行上下文替换...")
        search_query = _refine_query_with_context(raw_query, state, llm)
        print_kv("优化后查询", search_query[:80] + "..." if len(search_query) > 80 else search_query)
    else:
        search_query = raw_query

    # 3. 绑定 Google Search 工具
    search_llm = llm.bind_tools([{"google_search": {}}])

    # 4. 执行搜索
    try:
        messages = [
            SystemMessage(content=SEARCH_PROMPT.format(search_query=search_query)),
            HumanMessage(content=f"请搜索: {search_query}")
        ]
        response = search_llm.invoke(messages)
        search_result = response.content

        debug_print(f"[Search Agent] 搜索完成，结果长度: {len(search_result)} 字符")

    except Exception as e:
        debug_print(f"[Search Agent] 搜索失败: {e}")
        search_result = f"搜索失败: {str(e)}"

    # 5. 返回结果
    query_summary = search_query[:40] + "..." if len(search_query) > 40 else search_query

    # 展示数据更新
    print_trip_data_update("search_findings", {"query": query_summary, "result_len": len(search_result)})
    print_routing("search_agent", "supervisor", f"搜索完成: {query_summary}")

    return {
        "trip_data": {
            "search_findings": search_result,
            "search_query": search_query,  # 保存原始查询以便追溯
        },
        "messages": [AIMessage(
            content=f"[Search Agent] 已完成搜索: {query_summary}",
            name="search_agent"
        )]
    }
