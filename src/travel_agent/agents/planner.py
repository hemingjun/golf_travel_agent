"""Planner Agent - 意图精炼与任务拆解 (锚点逻辑最终版)"""

import json
import re
from typing import Literal
from datetime import datetime, timedelta
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from ..config import debug_print
from ..graph.state import GraphState


PLANNER_PROMPT = """你是高尔夫旅行领域的**逻辑分析专家**。
你的核心任务是识别用户查询的 **逻辑锚点 (Logic Anchor)**，从而决定检索策略。

## 系统环境
- **当前日期 (Today)**：{current_date}
- **明天 (Tomorrow)**：{tomorrow}
- **后天 (Day After)**：{day_after_tomorrow}

## 核心思维算法：锚点判定 (Anchor Detection)

在生成 JSON 前，你必须先在 `thought_trace` 中运行以下判定逻辑：

**判定 1：时间主导 (Time-Dominant) -> Slot Lookup (查槽位)**
- **特征**：用户的问题以“时间”为核心约束，询问该时间段内发生了什么。
- **典型问法**：
  - "明天有什么安排？"
  - "后天我们在哪里？" (注意：这里'哪里'是结果，'后天'是条件)
  - "18号早上干什么？"
- **执行策略 (TIME_ANCHOR)**：
  - 直接锁定特定日期 (Target Date)。
  - 任务重点是查询该日期的日程表。

**判定 2：空间主导 (Space-Dominant) -> Entity Matching (找实体)**
- **特征**：用户的问题以“事物/地点”为核心约束，询问该事物的属性（哪怕上下文里有时间）。
- **典型问法**：
  - "我们要去打球的地方呢？" (核心是找球场)
  - "皇家卡洛斯怎么去？" (核心是找皇家卡洛斯)
  - "那家酒店怎么样？"
- **执行策略 (SPACE_ANCHOR)**：
  - **解耦操作**：暂时忽略上下文中的“明天/后天”限制，不要只查明天的行程。
  - **全局扫描**：在**整个行程**中找到该实体 (Entity)。
  - **属性叠加**：找到实体后，再查询它在特定时间的状态（如天气）。

---
**🔥 关键辩证 (User Case Study)**
场景：用户在问明天天气，紧接着问：**"那我们要去打球的地方呢？"**

1. **分析主语**：用户的主语是“地方”(The Place)，而不是“明天”(The Day)。
2. **判定锚点**：这是一个 **空间主导 (Space-Dominant)** 的查询。
3. **错误路径 (时间主导)**：查“明天”的行程 -> 发现明天没球 -> ❌ 失败。
4. **正确路径 (空间主导)**：
   - Step 1: 在**所有行程**中搜索 type="Golf" 的地点 -> 找到 "Cabo Real (1月28日)"。
   - Step 2: 查询 "Cabo Real" 在 "明天" 的天气。
---

## 参数提取严格标准
1. **Key 必须为英文**: `location`, `dates`, `location_type`。
2. **日期必须计算**: 必须输出 ISO 列表 `["2026-01-16"]`。
3. **Location 必填**: 只要涉及查询，必须提取 `location`。

## 可用工具箱 (Agents)
- **itinerary_agent**: 查询行程 (可按日期查，也可按关键词搜实体)。
- **golf_agent**: 球场预订详情。
- **weather_agent**: 天气预报。
- **hotel_agent**: 酒店详情。
- **logistics_agent**: 车辆安排。

## 客户与行程摘要
- 客户: {customer_data}
- 行程数据概览: {trip_data_summary}
"""


class RefinedPlan(BaseModel):
    """Planner 输出的精炼计划"""
    
    # 1. 思维链 (强制 Gemini 思考)
    thought_trace: str = Field(
        description="思考过程：1.分析主语 2.判定逻辑锚点(Time vs Space) 3.确定检索范围(Global vs Local)。"
    )

    # 2. 锚点判定 (核心逻辑)
    logic_anchor: Literal["TIME_ANCHOR_SLOT_LOOKUP", "SPACE_ANCHOR_ENTITY_MATCH"] = Field(
        description="逻辑锚点判定：\n"
                    "- TIME_ANCHOR_SLOT_LOOKUP: 以时间为条件 (如'明天去哪')。查特定日期的槽位。\n"
                    "- SPACE_ANCHOR_ENTITY_MATCH: 以物体/地点为条件 (如'打球的地方')。需在全局行程中匹配实体。"
    )

    # 3. 策略选择
    analysis_strategy: Literal["TIME_FOCUSED", "SPACE_FOCUSED", "GENERAL"] = Field(
        description="分析策略：\n"
                    "- SPACE_FOCUSED: 对应 Entity Match (找地点/实体)。\n"
                    "- TIME_FOCUSED: 对应 Slot Lookup (查日程/时间)。\n"
                    "- GENERAL: 其他。"
    )

    original_query: str = Field(description="用户原始问题")
    understood_intent: str = Field(description="理解的用户意图")
    resolved_params: dict = Field(default_factory=dict, description="已解析的参数")
    pending_data: list[str] = Field(default_factory=list, description="需要获取的数据类型")
    task_sequence: list[str] = Field(default_factory=list, description="任务执行序列")


def planner_node(state: GraphState, llm: BaseChatModel) -> dict:
    """Planner 节点"""

    # 1. 日期计算 (Python 计算比 LLM 更准)
    today = datetime.now()
    try:
        current_date_str = state.get("current_date", today.strftime("%Y-%m-%d"))
        # 兼容中文日期格式清洗
        if "年" in current_date_str:
            match = re.search(r"(\d{4}).*?(\d{1,2}).*?(\d{1,2})", current_date_str)
            if match:
                y, m, d = match.groups()
                current_date_dt = datetime(int(y), int(m), int(d))
                current_date = f"{y}-{int(m):02d}-{int(d):02d}"
            else:
                current_date_dt = today
                current_date = today.strftime("%Y-%m-%d")
        else:
            current_date_dt = datetime.strptime(current_date_str, "%Y-%m-%d")
            current_date = current_date_str
    except ValueError:
        current_date_dt = today
        current_date = today.strftime("%Y-%m-%d")

    tomorrow = (current_date_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    day_after = (current_date_dt + timedelta(days=2)).strftime("%Y-%m-%d")

    # 2. 上下文准备
    trip_data = state.get("trip_data", {})
    customer_data = trip_data.get("customer", {}) or state.get("customer_data", {})
    
    # 防止 Date 对象导致序列化崩溃
    def safe_serialize(obj):
        if hasattr(obj, 'isoformat'): return obj.isoformat()
        return str(obj)

    customer_summary = json.dumps(customer_data, ensure_ascii=False, indent=2, default=safe_serialize)
    data_keys = [k for k in trip_data.keys() if k != "customer"]
    trip_summary = f"已有数据 keys: {data_keys}" if data_keys else "暂无行程数据"

    # 3. Prompt
    messages = [
        SystemMessage(
            content=PLANNER_PROMPT.format(
                current_date=current_date,
                tomorrow=tomorrow,
                day_after_tomorrow=day_after,
                customer_data=customer_summary,
                trip_data_summary=trip_summary,
            )
        ),
        *state["messages"],
    ]

    # 4. LLM 调用
    try:
        # 使用 Gemini 原生适配的 Structured Output
        structured_llm = llm.with_structured_output(RefinedPlan)
        plan: RefinedPlan = structured_llm.invoke(messages)
        
        refined_plan = plan.model_dump_json(ensure_ascii=False)
        
        # 调试打印：查看思维链
        debug_print(f"========== Planner Thought Trace ==========")
        debug_print(plan.thought_trace)
        debug_print(f"Anchor: {plan.logic_anchor} | Strategy: {plan.analysis_strategy}")
        debug_print(f"===========================================")

    except Exception as e:
        debug_print(f"[ERROR] Planner LLM 调用失败: {e}")
        # 兜底逻辑
        user_msg = ""
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                user_msg = msg.content
                break
        
        # 构造一个安全的空计划 (默认为时间主导以防万一)
        refined_plan = json.dumps({
            "thought_trace": "Fallback: LLM Error",
            "logic_anchor": "TIME_ANCHOR_SLOT_LOOKUP", 
            "analysis_strategy": "GENERAL",
            "original_query": user_msg,
            "understood_intent": user_msg,
            "resolved_params": {},
            "pending_data": [],
            "task_sequence": []
        }, ensure_ascii=False)

    return {
        "refined_plan": refined_plan,
        "messages": [AIMessage(content="[Planner] 意图分析完成", name="planner")],
        "next_step": "supervisor",
    }