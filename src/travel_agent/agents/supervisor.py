"""Supervisor Agent - 意图识别与任务路由"""

import json
from datetime import date, datetime
from langchain_core.messages import SystemMessage, AIMessage
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from ..graph.state import GraphState, RouteTarget


class DateEncoder(json.JSONEncoder):
    """JSON encoder for date/datetime objects"""

    def default(self, obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)


SUPERVISOR_PROMPT = """你是高尔夫旅行智能助手的调度中心。

## 职责
1. 分析用户意图
2. 决定由哪个专业 Agent 处理
3. 生成明确的任务指令

## 可用 Agent
- golf_agent: 高尔夫球场信息、Tee Time、打球安排
- hotel_agent: 酒店信息、房型、入住退房
- logistics_agent: 车辆调度、机场接送、行程间交通
- itinerary_agent: 行程大纲、日程汇总、整体安排
- final_responder: 所有信息已收集完毕，生成最终回复

## 决策原则
1. 简单查询直接路由到对应 Agent
2. 复合查询按依赖顺序逐个处理（一次只分发一个任务）
3. 信息已充足时路由到 final_responder
4. 不确定或信息缺失时也路由到 final_responder（让它反问用户）

## 当前已收集的数据
{trip_data}

请分析用户需求并决策。
"""


class SupervisorDecision(BaseModel):
    """Supervisor 决策结构"""

    next_agent: RouteTarget = Field(description="下一个处理节点")
    task: str = Field(description="分配的任务描述")
    reasoning: str = Field(description="决策理由")


def supervisor_node(state: GraphState, llm: BaseChatModel) -> dict:
    """Supervisor 节点 - 分析意图并路由

    注意：此函数需要 llm 参数，在 graph.py 中需要使用
    functools.partial(supervisor_node, llm=llm) 进行绑定
    """

    # 检查迭代次数（防止无限循环）
    iteration = state.get("iteration_count", 0)
    if iteration >= 5:
        return {
            "next_step": "final_responder",
            "supervisor_instructions": "已达到最大迭代次数，请总结已有信息回复用户",
            "iteration_count": iteration + 1,
        }

    # 构建上下文（增加容错）
    trip_data = state.get("trip_data", {})
    if trip_data:
        try:
            trip_data_str = json.dumps(trip_data, ensure_ascii=False, indent=2, cls=DateEncoder)
        except (TypeError, ValueError):
            trip_data_str = str(trip_data)
    else:
        trip_data_str = "暂无数据"

    messages = [
        SystemMessage(content=SUPERVISOR_PROMPT.format(trip_data=trip_data_str)),
        *state["messages"],
    ]

    # 调用 LLM 决策
    structured_llm = llm.with_structured_output(SupervisorDecision)
    decision: SupervisorDecision = structured_llm.invoke(messages)

    return {
        "next_step": decision.next_agent,
        "supervisor_instructions": decision.task,
        "iteration_count": iteration + 1,
        "messages": [
            AIMessage(
                content=f"[Supervisor] 路由到 {decision.next_agent}: {decision.task}",
                name="supervisor",
            )
        ],
    }
