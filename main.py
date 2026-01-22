"""高尔夫旅行智能助手入口

基于 ReAct Agent 的单一智能体架构，让 LLM 自主决定工具调用顺序。
"""

import sys
import uuid
from datetime import datetime
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

load_dotenv()
sys.path.insert(0, "src")

from travel_agent import create_graph
from travel_agent.utils import set_debug_mode
from travel_agent.tools import get_customer_info, validate_customer_access
from travel_agent.tools.itinerary import query_itinerary
from travel_agent.tools.weather import query_weather


def extract_text_content(content) -> str:
    """从 LLM 响应中提取纯文本内容（兼容 Gemini 3 多模态格式）"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
            elif isinstance(item, str):
                texts.append(item)
        return "\n".join(texts)
    return str(content)


def print_debug_node(node_name: str, output: dict):
    """格式化输出节点执行信息（调试用）"""
    print(f"\n[{node_name}]")

    # 消息内容
    if "messages" in output:
        for msg in output["messages"]:
            content = msg.content if hasattr(msg, "content") else str(msg)
            # 处理列表类型内容（多模态消息）
            if isinstance(content, list):
                content = " ".join(
                    str(c.get("text", c)) if isinstance(c, dict) else str(c)
                    for c in content
                )
            # 截断过长内容
            if len(content) > 500:
                content = content[:500] + "..."
            lines = content.split("\n")
            for line in lines[:10]:  # 最多显示 10 行
                print(f"  → {line}")

    # 工具调用
    messages = output.get("messages", [])
    if messages:
        last_msg = messages[-1]
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            for tc in last_msg.tool_calls:
                print(f"  → 调用工具: {tc.get('name', '?')}")


def main(
    trip_id: str = None,
    user_id: str = None,
    debug: bool = False,
):
    """主函数

    Args:
        trip_id: 行程 ID（Notion Page ID）
        user_id: 用户 ID（admin 为管理员模式，其他值为客户 page_id）
        debug: 调试模式，开启后显示思维链
    """
    is_admin = user_id == "admin"
    show_debug = is_admin or debug
    set_debug_mode(show_debug)
    customer_id = None if is_admin else user_id

    print("高尔夫旅行智能助手")
    print("=" * 40)
    if is_admin:
        print("[管理员模式] 将显示 Agent 思维链")
    elif debug:
        print("[调试模式] 将显示 Agent 思维链")

    # 客户模式：加载客户信息
    customer_data = None
    if customer_id:
        print("正在加载客户信息...")
        customer_data = get_customer_info(customer_id)
        if customer_data:
            print(f"欢迎，{customer_data.get('name', customer_data.get('全名', '客户'))}！")
            # 显示已记录的偏好
            dietary = customer_data.get("dietary_preferences", "")
            if dietary:
                print(f"饮食偏好：{dietary}")
            service_req = customer_data.get("service_requirements", "")
            if service_req:
                print(f"服务需求：{service_req}")
        else:
            print("错误：无法加载客户信息，请检查 user_id 是否正确")
            return

    if not trip_id:
        trip_id = input("请输入行程 ID (Notion Page ID): ").strip()
        if not trip_id:
            print("错误：需要提供行程 ID")
            return

    # 客户模式：验证客户是否有权访问该行程
    if customer_id:
        print("正在验证行程访问权限...")
        if not validate_customer_access(customer_id, trip_id):
            print("错误：您没有权限访问该行程")
            return
        print("权限验证通过")

    print(f"已绑定行程: {trip_id}")

    # 获取当前系统日期
    current_date = datetime.now().strftime("%Y年%m月%d日")

    # 创建 ReAct Agent 图（动态配置模式）
    graph = create_graph(checkpointer="memory")

    # 初始状态（仅 messages）
    initial_state = {
        "messages": [],
    }

    # 生成会话 ID，并在 config 中传递运行时参数
    thread_id = str(uuid.uuid4())
    config = {
        "configurable": {
            "thread_id": thread_id,
            "trip_id": trip_id,
            "customer_id": customer_id or "",
            "customer_info": customer_data,
            "current_date": current_date,
        }
    }

    # 启动时自动打招呼
    customer_name = customer_data.get("name", "客户") if customer_data else "管理员"

    # 直接调用工具获取今日数据（避免 Agent 推理延迟）
    print("正在获取今日信息...")

    # 获取今日行程（工具从 config 读取 trip_id）
    today_iso = datetime.now().strftime("%Y-%m-%d")
    itinerary_data = ""
    try:
        itinerary_data = query_itinerary.invoke({}, config=config)
    except Exception as e:
        itinerary_data = f"行程数据获取失败: {e}"

    # 获取今日天气（从行程中提取地点，默认 Los Cabos）
    weather_data = ""
    try:
        weather_data = query_weather.invoke({"location": "Los Cabos", "date": today_iso})
    except Exception as e:
        weather_data = f"天气数据获取失败: {e}"

    # 将数据传给 Agent 生成开场白（无需再调用工具）
    greeting_prompt = f"""[系统指令] 请基于以下信息和 {customer_name} 打个招呼：

**今日行程数据**:
{itinerary_data}

**今日天气**:
{weather_data}

请用温暖友好的语气：
1. 问候客户
2. 告知今天的安排（如有）
3. 提醒天气情况
4. 简要介绍你能提供的帮助（行程查询、天气、球场攻略等）

注意：不需要再调用工具，直接基于上面的数据生成回复。"""

    print("")
    greeting_state = {
        **initial_state,
        "messages": [HumanMessage(content=greeting_prompt)],
    }

    try:
        if show_debug:
            print("─" * 20 + " 思维链 " + "─" * 20)
            result = None
            for stream_mode, chunk in graph.stream(
                greeting_state, config, stream_mode=["updates", "values"]
            ):
                if stream_mode == "updates":
                    for node_name, node_output in chunk.items():
                        print_debug_node(node_name, node_output)
                elif stream_mode == "values":
                    result = chunk
            print("─" * 20 + " 思维链结束 " + "─" * 20)
        else:
            result = graph.invoke(greeting_state, config)

        last_message = result["messages"][-1]
        print(f"助手: {extract_text_content(last_message.content)}\n")
    except Exception as e:
        print(f"获取今日信息失败: {e}\n")
        if show_debug:
            import traceback
            traceback.print_exc()

    print("输入问题继续咨询，输入 'quit' 退出\n")

    while True:
        try:
            user_input = input("你: ").strip()
            if user_input.lower() in ("quit", "exit", "q"):
                print("再见！")
                break

            if not user_input:
                continue

            # 构建输入状态（checkpointer 会自动保持上下文）
            input_state = {
                "messages": [HumanMessage(content=user_input)],
            }

            # 执行图
            if show_debug:
                print("\n" + "─" * 20 + " 思维链 " + "─" * 20)
                result = None
                for stream_mode, chunk in graph.stream(
                    input_state, config, stream_mode=["updates", "values"]
                ):
                    if stream_mode == "updates":
                        for node_name, node_output in chunk.items():
                            print_debug_node(node_name, node_output)
                    elif stream_mode == "values":
                        result = chunk
                print("─" * 20 + " 思维链结束 " + "─" * 20)
            else:
                print("思考中...", end="", flush=True)
                result = graph.invoke(input_state, config)
                print("\r" + " " * 10 + "\r", end="")

            # 获取最终回复
            last_message = result["messages"][-1]
            print(f"助手: {extract_text_content(last_message.content)}\n")

        except KeyboardInterrupt:
            print("\n再见！")
            break
        except Exception as e:
            print(f"\n错误: {e}\n")
            if show_debug:
                import traceback
                traceback.print_exc()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="高尔夫旅行智能助手")
    parser.add_argument("--trip-id", "-t", help="行程 ID (Notion Page ID)")
    parser.add_argument(
        "--user-id", "-u",
        help="用户 ID（admin 为管理员模式，其他值为客户 page_id）"
    )
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="调试模式，显示 Agent 思维链"
    )
    args = parser.parse_args()

    main(args.trip_id, args.user_id, args.debug)
