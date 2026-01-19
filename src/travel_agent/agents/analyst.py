"""Analyst Agent - 逻辑分析与风控 (Gemini 适配 + 序列化修复版)"""

import json
from datetime import datetime, date
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


# --- JSON 序列化辅助函数 ---
def date_serializer(obj):
    """解决 Object of type date is not JSON serializable 问题"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


# --- 执行状态格式化函数 ---
def _format_execution_summary(procurement_plan: list[dict]) -> str:
    """格式化 procurement_plan 执行状态摘要

    Args:
        procurement_plan: 采购计划列表

    Returns:
        格式化的状态摘要字符串
    """
    if not procurement_plan:
        return "无采购计划"

    status_emoji = {
        "FILLED": "OK",
        "FAILED": "FAIL",
        "PENDING": "WAIT",
        "DISPATCHED": "RUN",
    }

    lines = ["数据采集状态:"]
    for slot in procurement_plan:
        status = slot.get("status", "?")
        emoji = status_emoji.get(status, "?")
        field_name = slot.get("field_name", "unknown")
        source_agent = slot.get("source_agent", "unknown")
        value = slot.get("value", "")

        # 截断过长的值
        value_preview = str(value)[:50] + "..." if value and len(str(value)) > 50 else str(value) if value else ""

        line = f"- [{emoji}] {field_name} ({source_agent}): {status}"
        if value_preview and status == "FILLED":
            line += f" = {value_preview}"
        lines.append(line)

    return "\n".join(lines)


ANALYST_PROMPT = """你是一个逻辑严密的高尔夫行程分析师。你的职责是基于现有数据，回答用户问题，并主动检测潜在风险。

## 系统环境
- **当前日期**：{current_date}

## 你的输入数据 (Context)
1. **用户问题**：{user_query}
2. **Planner 意图**：{planner_intent}
3. **客户画像**：{customer_data}
4. **行程数据**：{trip_data}
5. **外部搜索结果**：{search_findings}
6. **数据采集状态**：{execution_summary}

## 核心职责 (Critical Thinking)
在生成报告前，请在 `thought_trace` 中进行深度思考：

1. **事实核对与纠错 (重要)**：
   - **时间错位检测**：用户问的是"明天"，但行程数据里的活动在"下周"。
     -> **必须指出**："用户查询日期为[日期A]，但实际行程在[日期B]。"
   - **空数据推理**：如果 Planner 想查行程中的天气，但 Supervisor 说"没查到行程"。
     -> **不要直接说没数据**。请检查 `trip_data` 里是否有未来的行程？如果有，请告诉用户："您明天没有打球安排，您的第一场球其实是在 [日期] 的 [球场名]。"

2. **采集失败处理（重要 - 必须遵守）**：
   - 仔细检查数据采集状态中是否有 **FAIL** 项
   - 如果有 FAIL 项，**必须**在回答的【关键纠正】或【风险提示】中明确告知用户：
     "由于技术原因，无法获取 [字段名] 数据。"
   - **绝对禁止**：掩盖失败、编造数据、假装没看到
   - 如果关键数据采集失败，主动建议用户稍后重试或提供替代方案

3. **空值检测（新增）**：
   - 如果某个 Slot 的 value 包含 `[ABORT]` 或 `数据已获取，但无法提取`
   - 这意味着数据虽然标记为 OK/FILLED，但实际内容不可用
   - 在报告中说明："[字段名] 数据不完整，建议您手动确认。"

4. **风险检测**：
   - 天气风险：降水概率 > 40%？
   - 时间风险：转场时间够吗？

5. **数据完整性**：回答问题所需的数据齐了吗？

6. **搜索整合**：如果存在外部搜索结果，请将其与行程背景结合分析。
   - 例如：Search Agent 找到了好吃的餐厅，需确认它离球场/酒店远不远
   - 例如：Search Agent 提供了汇率信息，需结合行程预算给出建议
   - 例如：Search Agent 找到了球场攻略，需结合客户差点给出针对性建议

## 输出结构 (Markdown Report)
- **关键纠正**: (仅在发现时间/地点/理解偏差时显示)
- **直接回答**: 针对用户问题给出结论。
- **补充建议**: (如果发生了时间错位，主动提供正确日期的信息)

"""

class AnalysisResult(BaseModel):
    """Analyst 输出结构"""
    thought_trace: str = Field(description="你的逻辑推理过程")
    analysis_report: str = Field(description="最终生成的 Markdown 分析报告")


def analyst_node(state: GraphState, llm: BaseChatModel) -> dict:
    """Analyst 节点 - 逻辑分析"""

    # 节点入口标识
    print_node_enter("analyst")

    # 1. 准备上下文数据
    current_date = state.get("current_date", datetime.now().strftime("%Y-%m-%d"))
    
    # 提取用户最新问题
    user_query = "未知问题"
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            user_query = msg.content
            break
            
    # 提取 Planner 意图
    refined_plan_str = state.get("refined_plan", "{}")
    planner_intent = "未知"
    try:
        plan = json.loads(refined_plan_str)
        planner_intent = plan.get("understood_intent", "未知")
    except:
        pass

    # 提取数据
    trip_data = state.get("trip_data", {})
    customer_data = trip_data.get("customer", {}) or state.get("customer_data", {})

    # 提取搜索结果
    search_findings = trip_data.get("search_findings", "无")
    if isinstance(search_findings, dict):
        try:
            search_findings = json.dumps(search_findings, ensure_ascii=False, indent=2, default=date_serializer)
        except:
            search_findings = str(search_findings)

    # ⚠️ 修复核心：使用 default=date_serializer 处理日期对象
    try:
        trip_data_str = json.dumps(trip_data, ensure_ascii=False, indent=2, default=date_serializer)
        customer_data_str = json.dumps(customer_data, ensure_ascii=False, indent=2, default=date_serializer)
    except Exception as e:
        debug_print(f"[ERROR] JSON 序列化失败: {e}")
        trip_data_str = str(trip_data)  # 兜底：直接转字符串
        customer_data_str = str(customer_data)

    # 提取采购计划执行状态
    procurement_plan = state.get("procurement_plan", [])
    execution_summary = _format_execution_summary(procurement_plan)

    # 展示最终食谱状态
    print_recipe_status(procurement_plan, "最终食谱状态", show_summary=True)

    # 2. 构建 Prompt
    prompt_content = ANALYST_PROMPT.format(
        current_date=current_date,
        user_query=user_query,
        planner_intent=planner_intent,
        customer_data=customer_data_str,
        trip_data=trip_data_str,
        search_findings=search_findings,
        execution_summary=execution_summary,
    )

    # 必须包含 HumanMessage
    messages = [
        SystemMessage(content=prompt_content),
        HumanMessage(content="请根据上述上下文和数据，生成最终的分析报告。")
    ]

    # 3. 调用 LLM
    try:
        structured_llm = llm.with_structured_output(AnalysisResult)
        result: AnalysisResult = structured_llm.invoke(messages)
        
        report = result.analysis_report
        trace = result.thought_trace

        # 展示思维链
        print_thought_trace(trace)

    except Exception as e:
        print_error_msg("Analyst LLM 调用失败", str(e))
        report = (
            f"根据现有数据分析：\n"
            f"用户问题：{user_query}\n"
            f"系统提示：自动分析遇到技术问题，但根据行程数据，请检查您的出行日期是否正确。"
        )

    # 4. 返回
    print_routing("analyst", "responder", "分析完成")

    progress_msg = AIMessage(content="[Analyst] 分析报告已生成", name="analyst")

    return {
        "analysis_report": report,
        "messages": [progress_msg]
    }