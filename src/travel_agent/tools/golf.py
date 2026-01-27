"""高尔夫预订工具"""

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from ..utils.notion import DATABASES, get_client
from ._utils import _extract_text, format_tool_result

TOOL_NAME = "高尔夫预订"


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
    configurable = config.get("configurable", {})
    trip_id = configurable.get("trip_id", "")

    if not trip_id:
        return format_tool_result(TOOL_NAME, error="未提供行程 ID")

    client = get_client()
    bookings = client.query_pages(
        DATABASES["高尔夫组件"],
        filter={"property": "关联行程", "relation": {"contains": trip_id}},
        sorts=[{"property": "PlayDate", "direction": "ascending"}],
    )

    if not bookings:
        return format_tool_result(TOOL_NAME, empty_message="未找到高尔夫预订记录")

    results = []
    for b in bookings:
        props = b.get("properties", {})
        results.append(
            {
                "球场": _extract_text(props.get("中文名", "")),
                "日期": props.get("PlayDate", ""),
                "开球时间": _extract_text(props.get("Teetime", "")),
                "地址": _extract_text(props.get("地址", "")),
                "电话": _extract_text(props.get("电话", "")),
                "球童": props.get("Caddie", False),
                "球车": props.get("Buggie", False),
                "备注": _extract_text(props.get("Notes", "")),
            }
        )

    return format_tool_result(TOOL_NAME, data=results)
