"""Golf Agent - 高尔夫相关查询"""

from langchain_core.messages import AIMessage

from ..graph.state import GraphState
from ..tools.golf import get_golf_bookings
from ..debug import print_node_enter, print_routing, print_trip_data_update


def _extract_text(value) -> str:
    """从 Notion 属性值中提取纯文本

    处理 rich_text、rollup 等复杂格式，返回纯文本字符串。
    """
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        texts = []
        for item in value:
            if isinstance(item, dict):
                # 直接包含 plain_text
                if "plain_text" in item:
                    texts.append(item["plain_text"])
                # rich_text 嵌套格式
                elif "rich_text" in item:
                    for rt in item.get("rich_text", []):
                        if isinstance(rt, dict):
                            texts.append(rt.get("plain_text", ""))
                # text.content 格式
                elif "text" in item and isinstance(item["text"], dict):
                    texts.append(item["text"].get("content", ""))
        return "".join(texts)
    return str(value) if value else ""


def golf_agent(state: GraphState) -> dict:
    """处理高尔夫相关任务

    返回格式遵循增量更新原则：
    - trip_data: 只包含本 Agent 负责的字段（标准化英文 Key）
    - messages: 添加进度消息通知 Supervisor
    """
    # 节点入口标识
    print_node_enter("golf_agent")

    trip_id = state["trip_id"]

    # 调用工具获取数据
    bookings = get_golf_bookings(trip_id)

    # 转换为标准化英文 Key（供 Analyst/Weather Agent 使用）
    golf_bookings_formatted = []
    all_player_ids: set[str] = set()  # 收集所有球手 ID（用于去重统计）

    for b in bookings:
        props = b.get("properties", {})

        # 提取球手 ID 列表（relation 类型）
        player_ids = props.get("球手", [])
        if isinstance(player_ids, list):
            all_player_ids.update(player_ids)

        golf_bookings_formatted.append({
            "id": b.get("id", ""),
            "course_name": _extract_text(props.get("中文名", "")),
            "play_date": props.get("PlayDate", ""),
            "tee_time": _extract_text(props.get("Teetime", "")),
            "address": _extract_text(props.get("地址", "")),
            "phone": _extract_text(props.get("电话", "")),
            "caddie": props.get("Caddie", False),
            "buggy": props.get("Buggie", False),
            "notes": _extract_text(props.get("Notes", "")),
            "player_ids": player_ids if isinstance(player_ids, list) else [],
        })

    # 按日期+时间排序，空值排最后
    golf_bookings_formatted.sort(key=lambda x: (
        x.get("play_date") or "9999-99-99",
        x.get("tee_time") or "99:99",
    ))

    # 构建增量更新
    trip_data_update = {
        "golf_bookings": golf_bookings_formatted,
        "golf_count": len(bookings),
        "unique_player_count": len(all_player_ids),  # 去重后的球手数量
        "all_player_ids": list(all_player_ids),      # 所有球手 ID（便于后续查询详情）
    }

    # 构建进度消息
    if bookings:
        player_info = f"（共 {len(all_player_ids)} 位球手）" if all_player_ids else ""
        summary = f"[Golf Agent] 已获取 {len(bookings)} 条高尔夫预订记录{player_info}"
        details = []
        for item in golf_bookings_formatted:
            play_date = item.get("play_date") or "待定"
            tee_time = item.get("tee_time") or "待定"
            course = item.get("course_name") or "未知球场"
            player_count = len(item.get("player_ids", []))
            details.append(f"- [{play_date} {tee_time}] {course} ({player_count}人)")
        summary += "\n" + "\n".join(details)
    else:
        summary = "[Golf Agent] 未找到高尔夫预订记录"

    progress_msg = AIMessage(content=summary, name="golf_agent")

    # 展示数据更新
    print_trip_data_update("golf_bookings", golf_bookings_formatted)
    print_routing("golf_agent", "supervisor", f"获取 {len(bookings)} 条高尔夫预订")

    return {
        "trip_data": trip_data_update,
        "messages": [progress_msg],
    }
