"""Analyst Agent - 逻辑分析与风控 (Gemini 适配 + 序列化修复版)"""

import json
from datetime import datetime, date
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from ..config import debug_print
from ..graph.state import GraphState


# --- 新增：JSON 序列化辅助函数 ---
def date_serializer(obj):
    """解决 Object of type date is not JSON serializable 问题"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


ANALYST_PROMPT = """你是一个逻辑严密的高尔夫行程分析师。你的职责是基于现有数据，回答用户问题，并主动检测潜在风险。

## 系统环境
- **当前日期**：{current_date}

## 你的输入数据 (Context)
1. **用户问题**：{user_query}
2. **Planner 意图**：{planner_intent}
3. **客户画像**：{customer_data}
4. **行程数据**：{trip_data}

## 核心职责 (Critical Thinking)
在生成报告前，请在 `thought_trace` 中进行深度思考：

1. **事实核对与纠错 (重要)**：
   - **时间错位检测**：用户问的是"明天"，但行程数据里的活动在"下周"。
     -> **必须指出**："用户查询日期为[日期A]，但实际行程在[日期B]。"
   - **空数据推理**：如果 Planner 想查行程中的天气，但 Supervisor 说"没查到行程"。
     -> **不要直接说没数据**。请检查 `trip_data` 里是否有未来的行程？如果有，请告诉用户："您明天没有打球安排，您的第一场球其实是在 [日期] 的 [球场名]。"

2. **风险检测**：
   - 天气风险：降水概率 > 40%？
   - 时间风险：转场时间够吗？

3. **数据完整性**：回答问题所需的数据齐了吗？

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
    
    # ⚠️ 修复核心：使用 default=date_serializer 处理日期对象
    try:
        trip_data_str = json.dumps(trip_data, ensure_ascii=False, indent=2, default=date_serializer)
        customer_data_str = json.dumps(customer_data, ensure_ascii=False, indent=2, default=date_serializer)
    except Exception as e:
        debug_print(f"[ERROR] JSON 序列化失败: {e}")
        trip_data_str = str(trip_data) # 兜底：直接转字符串
        customer_data_str = str(customer_data)

    # 2. 构建 Prompt
    prompt_content = ANALYST_PROMPT.format(
        current_date=current_date,
        user_query=user_query,
        planner_intent=planner_intent,
        customer_data=customer_data_str,
        trip_data=trip_data_str
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
        
        debug_print(f"========== Analyst Thought Trace ==========")
        debug_print(trace)
        debug_print(f"===========================================")

    except Exception as e:
        debug_print(f"[ERROR] Analyst LLM 调用失败: {e}")
        report = (
            f"根据现有数据分析：\n"
            f"用户问题：{user_query}\n"
            f"系统提示：自动分析遇到技术问题，但根据行程数据，请检查您的出行日期是否正确。"
        )

    # 4. 返回
    progress_msg = AIMessage(content="[Analyst] 分析报告已生成", name="analyst")
    
    return {
        "analysis_report": report,
        "messages": [progress_msg]
    }