"""高尔夫预订工具"""

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from ..utils.notion import DATABASES, get_client
from ._utils import _extract_text


@tool
def query_golf_bookings(config: RunnableConfig) -> str:
    """查询高尔夫预订信息

    获取当前行程的所有高尔夫预订记录。

    返回信息包括：
    - 球场名称（中文名）
    - 打球日期和开球时间 (Teetime)
    - 球场地址和电话
    - 是否需要球童 (Caddie) 和球车 (Buggy)
    - 预订备注

    适用场景：
    - "明天打哪个球场？"
    - "几点开球？"
    - "球场地址在哪？"
    - "需要球童吗？"
    - "这次行程打几场球？"

    注意：
    - 结果按打球日期升序排列
    - 如需确定"第一场球"或"最后一场"，直接查看列表顺序即可
    """
    # 从 RunnableConfig 获取 trip_id
    configurable = config.get("configurable", {})
    trip_id = configurable.get("trip_id", "")

    if not trip_id:
        return "错误：未提供行程 ID，请确保在请求中包含 trip_id"

    client = get_client()
    bookings = client.query_pages(
        DATABASES["高尔夫组件"],
        filter={"property": "关联行程", "relation": {"contains": trip_id}},
        sorts=[{"property": "PlayDate", "direction": "ascending"}],
    )

    if not bookings:
        return "未找到高尔夫预订记录"

    results = []
    for b in bookings:
        props = b.get("properties", {})
        results.append(
            {
                "id": b.get("id", ""),
                "course_name": _extract_text(props.get("中文名", "")),
                "play_date": props.get("PlayDate", ""),
                "tee_time": _extract_text(props.get("Teetime", "")),
                "address": _extract_text(props.get("地址", "")),
                "phone": _extract_text(props.get("电话", "")),
                "caddie": props.get("Caddie", False),
                "buggy": props.get("Buggie", False),
                "notes": _extract_text(props.get("Notes", "")),
            }
        )

    output = f"找到 {len(results)} 条高尔夫预订:\n\n"
    for i, r in enumerate(results, 1):
        output += f"【第 {i} 场】{r['course_name']}\n"
        output += f"  日期: {r['play_date']}\n"
        output += f"  开球时间: {r['tee_time']}\n"
        if r["address"]:
            output += f"  地址: {r['address']}\n"
        if r["phone"]:
            output += f"  电话: {r['phone']}\n"
        output += f"  球童: {'是' if r['caddie'] else '否'}, 球车: {'是' if r['buggy'] else '否'}\n"
        if r["notes"]:
            output += f"  备注: {r['notes']}\n"
        output += "\n"

    return output
