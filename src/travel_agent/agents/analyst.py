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

### 1. 多源数据综合分析【重要 - 必须优先执行】

trip_data 中可能包含来自不同 Agent 的相关数据，你需要：

**识别所有相关数据源**：
- 同一个问题可能有多个数据来源（如球手数量可能来自 golf、logistics、customer）
- 逐一检查每个数据源的值

**评估可靠性并选择最佳答案**：
- 优先级：直接字段 > 关联字段 > 推算值
- 如果主数据源为空或 0，检查备选数据源
- 如果多个数据源都有数据，交叉验证是否一致

**示例场景**：
用户问："有多少球手？"
trip_data 包含：
- unique_player_count: 0（golf_agent - players 字段未填写）
- logistics 接送记录显示 4 人
- customer 行程关联 5 位客户

分析过程：
1. player_ids 未填写（0），无法直接获取
2. 接送记录显示 4 人去打球
3. 行程关联 5 位客户（可能包含非球手随行人员）
4. 结论：根据接送记录，**约 4 位球手**参与打球

### 2. 事实核对与纠错
- **时间错位检测**：用户问的是"明天"，但行程数据里的活动在"下周"。
  -> **必须指出**："用户查询日期为[日期A]，但实际行程在[日期B]。"
- **空数据推理**：如果 Planner 想查行程中的天气，但 Supervisor 说"没查到行程"。
  -> **不要直接说没数据**。请检查 `trip_data` 里是否有未来的行程？

### 3. 采集失败处理（必须遵守）
- 仔细检查数据采集状态中是否有 **FAIL** 项
- 如果有 FAIL 项，**必须**在回答中明确告知用户
- **绝对禁止**：掩盖失败、编造数据、假装没看到

### 4. 空值检测
- 如果某个 Slot 的 value 包含 `[ABORT]` 或 `数据已获取，但无法提取`
- 这意味着数据虽然标记为 OK/FILLED，但实际内容不可用
- 此时应检查是否有备选数据源可用

### 5. 风险检测
- 天气风险：降水概率 > 40%？
- 时间风险：转场时间够吗？

### 6. 搜索整合
如果存在外部搜索结果，请将其与行程背景结合分析。

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
        trace = f"[错误] LLM 调用失败: {str(e)}"

    # 4. 返回
    print_routing("analyst", "responder", "分析完成")

    progress_msg = AIMessage(content="[Analyst] 分析报告已生成", name="analyst")

    return {
        "analysis_report": report,
        "analyst_thought_trace": trace,  # 暴露思维链供 UI 使用
        "messages": [progress_msg]
    }