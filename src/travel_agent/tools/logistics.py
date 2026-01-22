"""物流接送工具"""

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from ..utils.notion import DATABASES, get_client


@tool
def query_logistics(config: RunnableConfig) -> str:
    """查询接送物流安排

    获取当前行程的交通接送信息。

    返回信息包括：
    - 日期和出发时间
    - 出发地和目的地
    - 车型
    - 人数
    - 预计行程时长

    适用场景：
    - "明天几点出发？"
    - "去机场的车几点来？"
    - "坐什么车？"
    - "从酒店到球场要多久？"

    注意：
    - 结果按日期和出发时间升序排列
    - 如果没有物流安排，可能需要查询高尔夫预订来推算出发时间
    """
    # 从 RunnableConfig 获取 trip_id
    configurable = config.get("configurable", {})
    trip_id = configurable.get("trip_id", "")

    if not trip_id:
        return "错误：未提供行程 ID，请确保在请求中包含 trip_id"

    client = get_client()
    arrangements = client.query_pages(
        DATABASES["物流组件"],
        filter={"property": "关联行程", "relation": {"contains": trip_id}},
        sorts=[{"property": "日期", "direction": "ascending"}],
    )

    if not arrangements:
        return "暂无物流安排数据。建议查询高尔夫预订获取开球时间，然后推算出发时间。"

    results = []
    for a in arrangements:
        props = a.get("properties", {})
        results.append(
            {
                "id": a.get("id"),
                "date": props.get("日期", ""),
                "departure_time": props.get("出发时间", ""),
                "origin": props.get("出发地", ""),
                "destination": props.get("目的地", ""),
                "vehicle_type": props.get("车型", ""),
                "pax": props.get("人数", ""),
                "duration_mins": props.get("行程时长(分钟)", ""),
            }
        )

    output = f"找到 {len(results)} 条接送安排:\n\n"
    for r in results:
        output += f"【{r['date']}】{r['departure_time']} 出发\n"
        output += f"  {r['origin']} → {r['destination']}\n"
        if r["vehicle_type"]:
            output += f"  车型: {r['vehicle_type']}\n"
        if r["pax"]:
            output += f"  人数: {r['pax']}\n"
        if r["duration_mins"]:
            output += f"  预计行程: {r['duration_mins']} 分钟\n"
        output += "\n"

    return output
