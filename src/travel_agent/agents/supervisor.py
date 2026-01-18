"""Supervisor Agent - 纯路由执行器"""

import json
from datetime import datetime
from langchain_core.messages import SystemMessage, AIMessage
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from ..config import debug_print
from ..graph.state import GraphState, RouteTarget, AnalysisStrategy



SUPERVISOR_PROMPT = """你是高尔夫旅行智能助手的调度中心（纯路由器）。

## 系统信息
- **当前日期**：{current_date}

## 决策依据（优先级从高到低）

### 1. Planner 意图分析（最高优先级）
{refined_plan}

**路由规则**：
如果 Planner 的 `pending_data` 非空，**必须优先**路由给对应 Worker：
- golf_bookings → golf_agent
- hotel_bookings → hotel_agent
- logistics → logistics_agent
- events/itinerary → itinerary_agent
- customer → customer_agent
- weather → weather_agent

### 2. 数据完整性检查
当前已拥有数据类型: {data_keys}

检查 Planner 的 `pending_data` 中的每一项是否已存在于上述 keys 中。
- 缺失 → 路由到对应 Agent
- 全部满足 → 路由到 analyst

### 3. 最终分析
仅当 `pending_data` 为空或全部数据已获取时，才路由到 analyst。

## 可用 Agent
- golf_agent: 球场信息、Tee Time
- hotel_agent: 酒店、房型
- logistics_agent: 车辆、接送
- itinerary_agent: 日程安排
- customer_agent: 客户档案
- weather_agent: 天气预报
- analyst: 综合分析（最终节点）
"""


class SupervisorDecision(BaseModel):
    """Supervisor 决策结构"""

    next_agent: RouteTarget = Field(description="下一个处理节点")
    task: str = Field(description="分配的任务描述")
    reasoning: str = Field(description="决策理由")
    strategy: AnalysisStrategy = Field(
        default="GENERAL",
        description="分析策略：TIME_FOCUSED(时间冲突检测)、SPACE_FOCUSED(地理动线分析)、GENERAL(综合)",
    )


def supervisor_node(state: GraphState, llm: BaseChatModel) -> dict:
    """Supervisor 节点 - 分析意图并路由

    注意：此函数需要 llm 参数，在 graph.py 中需要使用
    functools.partial(supervisor_node, llm=llm) 进行绑定
    """

    # 检查迭代次数（防止无限循环）
    iteration = state.get("iteration_count", 0)
    trip_data = state.get("trip_data", {})

    if iteration >= 5:
        return {
            "next_step": "analyst",
            "supervisor_instructions": "已达到最大迭代次数，请总结已有信息回复用户",
            "analysis_strategy": "GENERAL",
            "iteration_count": iteration + 1,
        }

    # Token 优化：只传递数据 keys，不传完整 JSON
    data_keys = list(trip_data.keys()) if trip_data else []
    data_keys_str = str(data_keys) if data_keys else "暂无数据"

    # 使用 state 中的当前日期
    current_date = state.get("current_date", datetime.now().strftime("%Y年%m月%d日"))

    # 获取 Planner 的精炼计划
    refined_plan = state.get("refined_plan", "{}")

    messages = [
        SystemMessage(content=SUPERVISOR_PROMPT.format(
            current_date=current_date,
            data_keys=data_keys_str,
            refined_plan=refined_plan,
        )),
        *state["messages"],
    ]

    # 调用 LLM 决策（添加错误处理）
    try:
        structured_llm = llm.with_structured_output(SupervisorDecision)
        decision: SupervisorDecision = structured_llm.invoke(messages)
    except Exception as e:
        debug_print(f"[ERROR] Supervisor LLM 调用失败: {e}")
        # 降级处理：直接路由到 analyst
        return {
            "next_step": "analyst",
            "supervisor_instructions": f"LLM 调用失败，降级到 analyst: {e}",
            "analysis_strategy": "GENERAL",
            "iteration_count": iteration + 1,
            "messages": [
                AIMessage(
                    content=f"[Supervisor] LLM 调用失败: {e}，降级路由到 analyst",
                    name="supervisor",
                )
            ],
        }

    # 从 refined_plan 提取 Planner 决定的策略（优先使用）
    try:
        plan_data = json.loads(refined_plan)
        planner_strategy = plan_data.get("analysis_strategy", decision.strategy)
    except (json.JSONDecodeError, TypeError):
        planner_strategy = decision.strategy

    next_agent = decision.next_agent

    # === 熔断机制：检测 Worker 连续失败 ===
    messages = state.get("messages", [])
    if messages:
        last_msg = messages[-1]
        last_msg_name = getattr(last_msg, "name", None)
        last_msg_content = getattr(last_msg, "content", "") or ""

        # 错误关键词检测
        error_keywords = ["无法获取", "无法识别", "失败", "Error", "错误", "缺少"]
        is_error = any(kw in last_msg_content for kw in error_keywords)

        # 如果上一轮是 Worker 报错，且这一轮 LLM 又要调同一个 Worker → 熔断
        if is_error and last_msg_name == next_agent:
            debug_print(f"[Supervisor] 熔断触发: {next_agent} 连续失败，强制路由到 analyst")
            return {
                "next_step": "analyst",
                "supervisor_instructions": f"[系统熔断] {next_agent} 任务失败，请根据现有信息总结回复用户",
                "analysis_strategy": "GENERAL",
                "iteration_count": iteration + 1,
                "messages": [
                    AIMessage(
                        content=f"[Supervisor] 熔断: {next_agent} 连续失败，强制路由到 analyst",
                        name="supervisor",
                    )
                ],
            }

    # 构建消息
    msg_content = (
        f"[Supervisor] 路由到 {next_agent}\n"
        f"  任务: {decision.task}\n"
        f"  策略: {planner_strategy}\n"
        f"  推理: {decision.reasoning}"
    )

    return {
        "next_step": next_agent,
        "supervisor_instructions": decision.task,
        "analysis_strategy": planner_strategy,  # 使用 Planner 决定的策略
        "iteration_count": iteration + 1,
        "messages": [AIMessage(content=msg_content, name="supervisor")],
    }
