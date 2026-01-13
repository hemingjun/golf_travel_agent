"""高尔夫旅行智能助手入口"""

import sys
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

load_dotenv()
sys.path.insert(0, "src")

from travel_agent import create_graph


def main(trip_id: str = None):
    """主函数

    Args:
        trip_id: 行程 ID（Notion Page ID）
    """
    print("高尔夫旅行智能助手")
    print("=" * 40)

    if not trip_id:
        trip_id = input("请输入行程 ID (Notion Page ID): ").strip()
        if not trip_id:
            print("错误：需要提供行程 ID")
            return

    print(f"已绑定行程: {trip_id}")
    print("输入问题开始咨询，输入 'quit' 退出\n")

    graph = create_graph()

    # 初始状态
    state = {
        "messages": [],
        "trip_id": trip_id,
        "trip_data": {},
        "next_step": "supervisor",
        "supervisor_instructions": "",
        "iteration_count": 0,
    }
    
    # 初始化对话历史
    chat_history = []

    while True:
        try:
            user_input = input("你: ").strip()
            if user_input.lower() in ("quit", "exit", "q"):
                print("再见！")
                break

            if not user_input:
                continue

            # 1. 将用户消息加入历史
            chat_history.append(HumanMessage(content=user_input))

            # 2. 传入完整历史
            state["messages"] = chat_history
            state["iteration_count"] = 0  # 重置迭代计数

            # 3. 执行图
            result = graph.invoke(state)

            # 4. 获取最终回复
            last_message = result["messages"][-1]
            print(f"\n助手: {last_message.content}\n")

            # 5. 继承 Graph 返回的完整消息历史
            chat_history = result["messages"]

            # 6. 保留 trip_data 用于下一轮对话
            state["trip_data"] = result.get("trip_data", {})

        except KeyboardInterrupt:
            print("\n再见！")
            break
        except Exception as e:
            print(f"\n错误: {e}\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="高尔夫旅行智能助手")
    parser.add_argument("--trip-id", "-t", help="行程 ID (Notion Page ID)")
    args = parser.parse_args()

    main(args.trip_id)
