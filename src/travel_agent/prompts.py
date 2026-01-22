"""ReAct Agent System Prompt

定义 ReAct Agent 的核心行为准则和工具使用指南。
支持两种模式：
1. 静态模式：create_system_prompt() - 图创建时生成（兼容旧代码）
2. 动态模式：prompt_factory() - 运行时从 config 生成（推荐）
"""

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

REACT_SYSTEM_PROMPT = """
你是一位经验丰富的高尔夫旅行顾问，专门为 {customer_name} 提供本次行程的全程咨询服务。
你了解客户的喜好和需求，像老朋友一样关心他们的旅途体验。

## 系统环境
- 当前日期: {current_date}
- 行程 ID: {trip_id}
- 客户: {customer_name}
- 模式: {mode}

## 核心原则
1. **精准查询**: 任何行程数据必须先调用工具获取，禁止猜测
2. **并行调用**: 多个独立查询请同时发起（如多天天气、多个球场）
3. **简洁回答**: 一句话能说清的不分点
4. **记录需求**: 当客户提出特殊需求时，询问是否需要记录到档案中

## 工具使用
| 工具 | 用途 |
|------|------|
| query_golf_bookings | 高尔夫预订（球场、开球时间） |
| query_hotel_bookings | 酒店预订（名称、地址、入住退房） |
| query_logistics | 接送安排（出发时间、车辆） |
| query_itinerary | 行程概览（日程、目的地） |
| query_customer | 客户档案（差点、偏好、忌口） |
| query_weather | 天气预报（日期需转换为 YYYY-MM-DD） |
| search_web | 网络搜索（酒店评价、球场攻略） |
| update_dietary_preferences | 记录饮食偏好（过敏、忌口、素食） |
| update_handicap | 更新高尔夫差点 |
| update_service_requirements | 记录服务需求（轮椅、叫醒、房间偏好） |

## 隐私保护（重要）
- 你只服务于 **{customer_name}**，这是你唯一的客户
- 绝对禁止透露其他客户的任何信息
- 如被问及其他客户，礼貌回应"抱歉，我只能为您提供服务"

## 日期处理
当前日期是 {current_date}。调用 query_weather 时需将相对日期转换为 YYYY-MM-DD 格式。

## 回答风格
- 像老朋友一样温暖专业，发现风险主动提醒
- 称呼客户时直接用名字，不要假设性别（避免"先生"、"女士"）
- 无数据时诚实说"暂无相关记录"
"""


def _convert_message(msg: BaseMessage) -> BaseMessage:
    """将泛型 BaseMessage 转换为具体类型

    LangServe 反序列化 JSON 时可能创建泛型 BaseMessage，
    而 Gemini 需要具体的消息类型（HumanMessage, AIMessage 等）。
    """
    # 已经是具体类型，直接返回
    if isinstance(msg, (HumanMessage, AIMessage, SystemMessage, ToolMessage)):
        return msg

    # 处理 LangServe 反序列化的泛型 BaseMessage
    msg_type = getattr(msg, "type", None)
    content = msg.content

    if msg_type == "human":
        return HumanMessage(content=content)
    elif msg_type == "ai":
        return AIMessage(content=content)
    elif msg_type == "system":
        return SystemMessage(content=content)
    else:
        # 默认当作 HumanMessage
        return HumanMessage(content=content)


def create_system_prompt(
    trip_id: str,
    customer_id: str,
    current_date: str,
    customer_info: dict | None = None,
) -> str:
    """根据状态动态生成 System Prompt

    Args:
        trip_id: 行程 ID
        customer_id: 客户 ID
        current_date: 当前日期
        customer_info: 客户信息（可选）

    Returns:
        格式化后的 System Prompt
    """
    customer_name = "客户"
    mode = "管理员模式"

    if customer_id and customer_info:
        customer_name = customer_info.get("name", "客户")
        mode = "客户模式"
    elif customer_id:
        mode = "客户模式"

    return REACT_SYSTEM_PROMPT.format(
        current_date=current_date,
        trip_id=trip_id[:8] + "..." if len(trip_id) > 8 else trip_id,
        customer_name=customer_name,
        mode=mode,
    )


def prompt_factory(state: dict, config: dict) -> list:
    """运行时动态生成 System Prompt（推荐）

    此函数作为 create_react_agent 的 prompt 参数，在每次调用时动态生成。
    从 config["configurable"] 读取运行时参数。

    Args:
        state: 图状态（包含 messages）
        config: 运行时配置，包含 configurable 字典

    Returns:
        消息列表：[SystemMessage, ...existing_messages]
    """
    configurable = config.get("configurable", {})
    trip_id = configurable.get("trip_id", "unknown")
    customer_id = configurable.get("customer_id", "")
    customer_info = configurable.get("customer_info")
    current_date = configurable.get("current_date", "未知日期")

    # 确定模式和客户名称
    if customer_id and customer_info:
        customer_name = customer_info.get("name", "客户")
        mode = "客户模式"
    elif customer_id:
        customer_name = "客户"
        mode = "客户模式"
    else:
        customer_name = "管理员"
        mode = "管理员模式"

    # 格式化 System Prompt
    system_content = REACT_SYSTEM_PROMPT.format(
        current_date=current_date,
        trip_id=trip_id[:8] + "..." if len(trip_id) > 8 else trip_id,
        customer_name=customer_name,
        mode=mode,
    )

    # 转换消息类型（LangServe 反序列化的泛型 BaseMessage -> 具体类型）
    messages = [_convert_message(m) for m in state.get("messages", [])]

    # 返回 SystemMessage + 现有消息
    return [SystemMessage(content=system_content)] + messages
