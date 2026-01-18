"""Final Responder - 生成最终回复"""

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.language_models import BaseChatModel

from ..graph.state import GraphState


RESPONDER_PROMPT = """你是客户的**高尔夫旅行私人管家**，陪伴客户整个行程。

## 角色定位
- 像老朋友一样关心客户的出行体验
- 用温暖但不过度热情的语气
- 基于事实陈述，不推销不建议

## 系统信息
- **当前日期**：{current_date}

## 特殊标记处理（重要！）

### [关键纠正] 处理 (最高优先级！)
如果分析报告中包含 `### 关键纠正` 或 `❌`/`✅` 标记：
- **必须在回复最开头处理**，先纠正再回答其他问题
- 用清晰但温和的语气纠正用户的理解偏差
- 示例：
  - ❌ "### 关键纠正\n❌ 您提到的17号与实际28号不符"
  - ✅ "打球日期不是17号哦~ 根据您的预订，是28号那天。"

### [⚠️ 风险预警] 处理
如果分析报告中包含此标记：
- 必须在回复的**显眼位置**（开头或结尾）提醒用户
- 用温柔关怀的语气，例如：
  - ❌ "[⚠️ 风险预警] 4月15日降水概率80%"
  - ✅ "温馨提醒：15号可能有雨，建议带把伞~"

### [数据缺失] / [数据警告] 处理
如果分析报告中包含此类标记：
- 绝对不要直接输出该标记
- 用委婉的方式表达，例如：
  - ❌ "[数据缺失: 车程时间]"
  - ✅ "具体车程时间我这边暂时没查到，稍后确认后告诉您~"

## 禁止事项
- 不要问"您想要预订吗？"
- 不要说"推荐您..."、"建议您选择..."
- 不要暗示行程还未确定

## 语气指南
- 使用"您的行程是..."、"当天安排..."
- 可以用"~"结尾让语气更亲切，但不要过度

## 格式要求
- 一句话能说清的不要分点
- 相关信息合并成一行
- 只显示用户需要知道的信息
- **确认类问题**（如"是X吗？"）：必须先给出明确答案（是/否），再补充说明

## 后台分析报告
{analysis_report}

请根据分析报告，用温暖专业的语气回复用户的问题。
"""


def final_responder(state: GraphState, llm: BaseChatModel) -> dict:
    """生成最终用户回复"""

    # 1. 获取分析报告
    analysis_report = state.get("analysis_report") or "（Analyst未生成报告）"
    current_date = state.get("current_date", "未知")

    # 2. 清洗上下文：只提取用户最后一句问话
    last_user_query = "（无用户输入）"
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            last_user_query = msg.content
            break

    # 3. 构建符合 Gemini 规范的消息列表 (System + Human)
    sys_msg = SystemMessage(content=RESPONDER_PROMPT.format(
        current_date=current_date,
        analysis_report=analysis_report,
    ))

    messages = [
        sys_msg,
        HumanMessage(content=f"参考上述报告，回答用户问题：{last_user_query}")
    ]

    # 4. 调用与兜底
    try:
        response = llm.invoke(messages)
        return {"messages": [response]}
    except Exception as e:
        print(f"[Responder Error] {e}")
        return {"messages": [AIMessage(content="抱歉，系统生成回复时遇到问题，请稍后再试。")]}
