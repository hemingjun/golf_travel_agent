"""行程信息工具"""

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from ..utils.notion import DATABASES, get_client


@tool
def query_itinerary(config: RunnableConfig) -> str:
    """查询行程信息和日程事件

    获取行程基本信息和所有事件安排。

    返回信息包括：
    - 行程名称、日期范围、人数
    - 每日事件列表（类型、内容）

    适用场景：
    - "这次行程几天？"
    - "今天有什么安排？"
    - "行程概览"
    - "这次去哪里？"（从行程名称或事件中获取地点）

    注意：
    - 这是获取行程地点信息的主要来源
    - 查询天气时，应先用此工具确定目的地
    """
    # 从 RunnableConfig 获取 trip_id
    configurable = config.get("configurable", {})
    trip_id = configurable.get("trip_id", "")

    if not trip_id:
        return "错误：未提供行程 ID，请确保在请求中包含 trip_id"

    client = get_client()

    trip_info = client.get_page(trip_id)
    props = trip_info.get("properties", {})
    trip_name = props.get("Name", "未知行程")
    trip_date = props.get("项目日期", "")
    trip_type = props.get("项目类型", "")
    pax = props.get("人数", 0)

    events = client.query_pages(
        DATABASES["行程组件"],
        filter={"property": "行程", "relation": {"contains": trip_id}},
        sorts=[{"property": "日期", "direction": "ascending"}],
    )

    output = "【行程信息】\n"
    output += f"名称: {trip_name}\n"
    output += f"日期: {trip_date}\n"
    output += f"类型: {trip_type}\n"
    output += f"人数: {pax}\n\n"

    if events:
        output += f"【日程安排】共 {len(events)} 个事件:\n\n"
        for e in events:
            e_props = e.get("properties", {})
            e_date = e_props.get("日期", "")
            e_type = e_props.get("事件类型", "")
            e_content = e_props.get("事件内容", "")
            output += f"  [{e_date}] {e_type}: {e_content}\n"
    else:
        output += "暂无日程事件数据"

    return output
