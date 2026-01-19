"""高尔夫旅行智能助手入口"""

import sys
import uuid
from datetime import datetime
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

load_dotenv()
sys.path.insert(0, "src")

from travel_agent import create_graph
from travel_agent.debug import set_debug_mode
from travel_agent.tools.customer import get_customer_info, validate_customer_access


def print_debug_node(node_name: str, output: dict):
    """格式化输出节点执行信息（管理员调试用）"""
    print(f"\n[{node_name}]")

    # 路由决策
    if "next_step" in output:
        print(f"  → 路由: {output['next_step']}")
    if "supervisor_instructions" in output:
        print(f"  → 任务: {output['supervisor_instructions']}")

    # 消息内容
    if "messages" in output:
        for msg in output["messages"]:
            content = msg.content if hasattr(msg, "content") else str(msg)
            # 缩进多行消息
            lines = content.split("\n")
            for line in lines:
                print(f"  → {line}")

    # 数据更新
    if "trip_data" in output and output["trip_data"]:
        keys = list(output["trip_data"].keys())
        print(f"  → 数据更新: {keys}")


def main(trip_id: str = None, user_id: str = None, debug: bool = False):
    """主函数

    Args:
        trip_id: 行程 ID（Notion Page ID）
        user_id: 用户 ID（admin 为管理员模式，其他值为客户 page_id）
        debug: 调试模式，开启后显示思维链
    """
    # 判断是否为管理员模式
    is_admin = user_id == "admin"
    # 调试模式：管理员默认开启，或通过 --debug 参数开启
    show_debug = is_admin or debug
    set_debug_mode(show_debug)  # 设置全局调试模式
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
            print(f"欢迎，{customer_data.get('全名', '客户')}！")
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
    print("输入问题开始咨询，输入 'quit' 退出\n")

    # 创建图（启用 MemorySaver 支持多轮对话）
    graph = create_graph(checkpointer="memory")

    # 生成会话 ID（用于 MemorySaver 追踪状态）
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    # 获取当前系统日期
    current_date = datetime.now().strftime("%Y年%m月%d日")

    # 初始状态（首次调用时传入，后续由 checkpointer 自动维护）
    initial_state = {
        "messages": [],
        "trip_id": trip_id,
        "customer_id": customer_id or "",
        "current_date": current_date,
        "trip_data": {"customer": customer_data} if customer_data else {},
        "next_step": "supervisor",
        "supervisor_instructions": "",
        "iteration_count": 0,
    }

    # 标记是否为首次调用
    first_call = True

    while True:
        try:
            user_input = input("你: ").strip()
            if user_input.lower() in ("quit", "exit", "q"):
                print("再见！")
                break

            if not user_input:
                continue

            # 构建输入状态
            if first_call:
                # 首次调用：传入完整初始状态 + 用户消息
                input_state = {
                    **initial_state,
                    "messages": [HumanMessage(content=user_input)],
                }
                first_call = False
            else:
                # 后续调用：只需传入新消息和重置迭代计数（其他状态由 checkpointer 维护）
                input_state = {
                    "messages": [HumanMessage(content=user_input)],
                    "iteration_count": 0,
                }

            # 执行图（传入 config 启用状态持久化）
            if show_debug:
                # 调试模式：使用 stream 实时输出思维链
                print("\n" + "─" * 20 + " 思维链 " + "─" * 20)
                result = None
                for mode, chunk in graph.stream(input_state, config, stream_mode=["updates", "values"]):
                    if mode == "updates":
                        for node_name, node_output in chunk.items():
                            print_debug_node(node_name, node_output)
                    elif mode == "values":
                        result = chunk
                print("─" * 20 + " 思维链结束 " + "─" * 20)
            else:
                # 普通模式：显示思考提示
                print("思考中...", end="", flush=True)
                result = graph.invoke(input_state, config)
                print("\r" + " " * 10 + "\r", end="")

            # 获取最终回复
            last_message = result["messages"][-1]
            print(f"助手: {last_message.content}\n")

            # 状态由 MemorySaver 自动维护，无需手动更新

        except KeyboardInterrupt:
            print("\n再见！")
            break
        except Exception as e:
            print(f"\n错误: {e}\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="高尔夫旅行智能助手")
    parser.add_argument("--trip-id", "-t", help="行程 ID (Notion Page ID)")
    parser.add_argument("--user-id", "-u", help="用户 ID（admin 为管理员模式，其他值为客户 page_id）")
    parser.add_argument("--debug", "-d", action="store_true", help="调试模式，显示 Agent 思维链")
    args = parser.parse_args()

    main(args.trip_id, args.user_id, args.debug)
