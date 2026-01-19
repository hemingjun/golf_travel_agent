"""Planner Agent - 意图精炼与任务拆解 (数据配方优化版)"""

import json
import re
from typing import Literal
from datetime import datetime, timedelta
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from ..debug import (
    debug_print,
    print_recipe_status,
    print_node_enter,
    print_thought_trace,
    print_routing,
    print_error_msg,
)
from ..graph.state import GraphState
from ..config.data_schema import format_field_ownership_for_prompt


PLANNER_PROMPT = """你是高尔夫旅行领域的**数据架构师**。
你的核心能力是**依赖感知的数据工程 (Dependency-Aware Data Engineering)**：从用户的问题反推所需的底层数据字段，并构建正确的依赖图谱。

## 系统环境
- **当前日期**：{current_date}
- **未来两天**：{tomorrow}, {day_after_tomorrow}

---

## 核心思维：依赖图谱构建 (Dependency Graph)

你必须生成一个 **采购计划 (procurement_plan)**，这是一个 DataSlot 列表。每个 DataSlot 描述一个需要采集的数据项及其依赖关系。

**关键规则：依赖必须显式声明**
- 如果你要搜"评价"，必须先有一个"实体名"
- 因此，"搜评价" Slot **必须依赖** "获取实体名" Slot
- 被依赖的 Slot 必须排在依赖者之前

---

## Step 1: 拆解变量 (Variable Decomposition)
分析用户问题，确定回答该问题所需的**具体字段**。
- 问："几点起床？" -> 核心变量是 `departure_time`，其次是 `tee_time`
- 问："那家酒店怎么样？" -> 先需要 `hotel_name`，然后才是 `reviews`

## Step 2: 依赖分析 (Dependency Analysis)
构建变量之间的依赖关系：
- `reviews` 依赖于 `hotel_name`（不知道酒店名就无法搜索评价）
- `weather` 依赖于 `location`（不知道地点就无法查天气）
- `tips` 依赖于 `course_name`（不知道球场名就无法搜索攻略）

## Step 3: 字段溯源 (Field Sourcing)
查阅 **[字段归属表]**，确定每个变量的数据源：
- ❌ 错误：去 `itinerary_agent` 找酒店详情（那里只有 ID）
- ✅ 正确：去 `hotel_agent` 找 `hotel_name`

## Step 4: 生成采购计划 (Generate procurement_plan)
按**拓扑排序**生成 DataSlot 列表：被依赖的 slot 在前，依赖者在后。

---

## 字段归属表 (FIELD_OWNERSHIP_MAP) - 绝对真理

{field_ownership_table}

---

## 示例 1：酒店评价（单依赖）

**用户问题**: "我住的酒店评价怎么样？"

**采购计划**:
```json
[
  {{"id": "req_hotel_name", "field_name": "hotel_name", "description": "获取入住酒店的具体名称", "source_agent": "hotel_agent", "dependencies": []}},
  {{"id": "req_reviews", "field_name": "reviews", "description": "搜索酒店的网上评价", "source_agent": "search_agent", "dependencies": ["req_hotel_name"]}}
]
```

## 示例 2：多数据源（无依赖）

**用户问题**: "明天几点出发打球？"

**采购计划**:
```json
[
  {{"id": "req_departure", "field_name": "departure_time", "description": "获取出发时间", "source_agent": "logistics_agent", "dependencies": []}},
  {{"id": "req_tee_time", "field_name": "tee_time", "description": "获取开球时间", "source_agent": "golf_agent", "dependencies": []}}
]
```

## 示例 3：多依赖

**用户问题**: "明天打球的天气和球场攻略"

**采购计划**:
```json
[
  {{"id": "req_course", "field_name": "course_name", "description": "获取球场名称", "source_agent": "golf_agent", "dependencies": []}},
  {{"id": "req_location", "field_name": "location", "description": "获取目的地位置", "source_agent": "itinerary_agent", "dependencies": []}},
  {{"id": "req_weather", "field_name": "weather", "description": "查询天气预报", "source_agent": "weather_agent", "dependencies": ["req_location"]}},
  {{"id": "req_tips", "field_name": "tips", "description": "搜索球场攻略", "source_agent": "search_agent", "dependencies": ["req_course"]}}
]
```

---

## 锚点判定
- **TIME_ANCHOR_SLOT_LOOKUP**: 用户问题包含时间词（明天、后天、几点）
- **SPACE_ANCHOR_ENTITY_MATCH**: 用户问题指向具体实体（酒店、球场）

## 客户与行程摘要
- 客户: {customer_data}
- 行程现有数据: {trip_data_summary}
"""


# --- Pydantic 模型定义 ---


class DataSlotSpec(BaseModel):
    """数据槽位规格（Planner 输出）- 支持依赖关系"""

    id: str = Field(description="唯一标识，格式如 req_hotel_name, req_reviews")
    field_name: str = Field(description="目标字段名，如 hotel_name, reviews")
    description: str = Field(description="任务描述，如 '获取入住酒店的具体名称'")
    source_agent: str = Field(description="执行 Agent，如 hotel_agent, search_agent")
    dependencies: list[str] = Field(
        default_factory=list,
        description="依赖的 Slot ID 列表。如搜索评价依赖酒店名：['req_hotel_name']"
    )


class RefinedPlan(BaseModel):
    """Planner 输出的精炼计划（依赖感知版）"""

    # 1. 思维链
    thought_trace: str = Field(
        description="思考过程：1.变量拆解 2.依赖分析 3.字段溯源 4.生成采购计划"
    )

    # 2. 锚点与源判定
    logic_anchor: Literal["TIME_ANCHOR_SLOT_LOOKUP", "SPACE_ANCHOR_ENTITY_MATCH"] = Field(...)
    data_source: Literal["PRIVATE_DB", "PUBLIC_WEB", "MIXED"] = Field(...)
    analysis_strategy: Literal["TIME_FOCUSED", "SPACE_FOCUSED", "GENERAL"] = Field(...)

    # 3. 采购计划（DAG 核心）
    procurement_plan: list[DataSlotSpec] = Field(
        description="数据槽位列表，按依赖拓扑排序。被依赖的 slot 在前，依赖者在后。"
    )

    # 4. 意图元信息
    original_query: str = Field(...)
    understood_intent: str = Field(...)
    resolved_params: dict = Field(default_factory=dict)
    pending_data: list[str] = Field(default_factory=list)


def planner_node(state: GraphState, llm: BaseChatModel) -> dict:
    """Planner 节点"""

    # 节点入口标识
    print_node_enter("planner")

    # 1. 日期处理
    today = datetime.now()
    try:
        current_date_str = state.get("current_date", today.strftime("%Y-%m-%d"))
        # ... (保留原有的日期清洗代码) ...
        # 为节省篇幅，此处省略具体的日期清洗逻辑，与之前一致
        current_date_dt = today # 兜底
        if "年" not in current_date_str:
             current_date_dt = datetime.strptime(current_date_str, "%Y-%m-%d")
        current_date = current_date_str
    except:
        current_date = today.strftime("%Y-%m-%d")
        current_date_dt = today

    tomorrow = (current_date_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    day_after = (current_date_dt + timedelta(days=2)).strftime("%Y-%m-%d")

    # 2. 上下文
    trip_data = state.get("trip_data", {})
    customer_data = trip_data.get("customer", {}) or state.get("customer_data", {})
    
    def safe_serialize(obj):
        if hasattr(obj, 'isoformat'): return obj.isoformat()
        return str(obj)

    customer_summary = json.dumps(customer_data, ensure_ascii=False, indent=2, default=safe_serialize)
    data_keys = [k for k in trip_data.keys() if k != "customer"]
    trip_summary = f"Existing Keys: {data_keys}"

    # 3. Prompt 构建
    messages = [
        SystemMessage(
            content=PLANNER_PROMPT.format(
                current_date=current_date,
                tomorrow=tomorrow,
                day_after_tomorrow=day_after,
                customer_data=customer_summary,
                trip_data_summary=trip_summary,
                field_ownership_table=format_field_ownership_for_prompt(), # 确保你引入了这个函数
            )
        ),
        *state["messages"],
    ]

    # 4. LLM 调用
    try:
        structured_llm = llm.with_structured_output(RefinedPlan)
        plan: RefinedPlan = structured_llm.invoke(messages)

        refined_plan = plan.model_dump_json(ensure_ascii=False)

        # 转换 DataSlotSpec → DataSlot（添加 status 和 value）
        procurement_plan = [
            {
                "id": slot.id,
                "field_name": slot.field_name,
                "description": slot.description,
                "source_agent": slot.source_agent,
                "dependencies": slot.dependencies,
                "status": "PENDING",
                "value": None,
                "_replace": True,  # 标记全量替换（仅第一个元素需要）
            }
            for slot in plan.procurement_plan
        ]

        # 展示思维链
        print_thought_trace(plan.thought_trace)

        # 展示初始食谱
        print_recipe_status(procurement_plan, "初始食谱")

    except Exception as e:
        print_error_msg("Planner 失败", str(e))
        # 兜底
        refined_plan = json.dumps(
            {
                "thought_trace": "Error",
                "logic_anchor": "TIME_ANCHOR_SLOT_LOOKUP",
                "data_source": "PRIVATE_DB",
                "analysis_strategy": "GENERAL",
                "procurement_plan": [],
                "original_query": "Error",
                "understood_intent": "Error",
            },
            ensure_ascii=False,
        )
        procurement_plan = []

    # 路由决策
    print_routing("planner", "supervisor", "计划已生成")

    return {
        "refined_plan": refined_plan,
        "procurement_plan": procurement_plan,
        "messages": [AIMessage(content="[Planner] 依赖图谱已生成", name="planner")],
        "next_step": "supervisor",
    }