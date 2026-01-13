"""Final Responder - 生成最终回复"""

import json
from datetime import date, datetime
from langchain_core.messages import SystemMessage, AIMessage
from langchain_core.language_models import BaseChatModel

from ..graph.state import GraphState


class DateEncoder(json.JSONEncoder):
    """JSON encoder for date/datetime objects"""

    def default(self, obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)


RESPONDER_PROMPT = """你是高尔夫旅行智能助手，负责向客户提供友好、专业的回复。

## 当前行程数据
{trip_data}

## 回复原则
1. 友好亲切，使用适当的敬语
2. 信息清晰有条理
3. 重要信息（时间、地点）要突出
4. 如果数据不足以回答问题，友好地请求用户提供更多信息
5. 建立数据之间的联系（如：因为A所以B）
6. 如果是行程安排类问题，可以使用表格展示

## 回复格式
- 先直接回应用户问题
- 列出相关信息
- 如有后续建议，友好提示

请根据收集到的行程数据生成回复。
"""


def final_responder(state: GraphState, llm: BaseChatModel) -> dict:
    """生成最终用户回复"""

    # 构建上下文
    trip_data = state.get("trip_data", {})
    trip_data_str = json.dumps(trip_data, ensure_ascii=False, indent=2, cls=DateEncoder) if trip_data else "暂无数据"

    messages = [
        SystemMessage(content=RESPONDER_PROMPT.format(trip_data=trip_data_str)),
        *state["messages"],
    ]

    # 调用 LLM 生成回复
    response = llm.invoke(messages)

    return {
        "messages": [response],
    }
