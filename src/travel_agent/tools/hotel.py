"""酒店预订工具"""

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from ..utils.debug import debug_print
from ..utils.notion import DATABASES, SCHEMAS, get_client, transform_props


@tool
def query_hotel_bookings(config: RunnableConfig) -> str:
    """查询酒店预订信息

    获取当前行程的酒店预订记录。

    返回信息包括：
    - 酒店名称和地址
    - 入住/退房日期
    - 房型和房间等级
    - 确认号

    适用场景：
    - "我住哪个酒店？"
    - "酒店地址在哪？"
    - "什么时候退房？"
    - "订的什么房型？"

    注意：
    - 如果是客户模式，只返回该客户的预订
    - 结果按入住日期升序排列
    - 如需查询酒店评价，请先用此工具获取酒店名称，再调用 search_web
    """
    # 从 RunnableConfig 获取 trip_id 和 customer_id
    configurable = config.get("configurable", {})
    trip_id = configurable.get("trip_id", "")
    customer_id = configurable.get("customer_id", "")

    if not trip_id:
        return "错误：未提供行程 ID，请确保在请求中包含 trip_id"

    client = get_client()

    if customer_id:
        filter_condition = {
            "and": [
                {"property": "关联行程", "relation": {"contains": trip_id}},
                {"property": "客户", "relation": {"contains": customer_id}},
            ]
        }
    else:
        filter_condition = {
            "property": "关联行程",
            "relation": {"contains": trip_id},
        }

    bookings = client.query_pages(
        DATABASES["酒店组件"],
        filter=filter_condition,
        sorts=[{"property": "入住日期", "direction": "ascending"}],
    )

    if not bookings:
        return "未找到酒店预订记录"

    results = []
    for b in bookings:
        props = b.get("properties", {})

        hotel_ids = props.get("酒店", [])
        hotel_info = {}
        if hotel_ids:
            try:
                page = client.get_page(hotel_ids[0])
                h_props = page.get("properties", {})
                hotel_info = transform_props(h_props, SCHEMAS.get("酒店", {}))
            except Exception as e:
                debug_print(f"[Hotel Tool] 获取酒店详情失败: {e}")

        results.append(
            {
                "id": b.get("id"),
                "hotel_name": hotel_info.get("name_cn")
                or hotel_info.get("name_en")
                or "未知酒店",
                "address": hotel_info.get("address", ""),
                "check_in": props.get("入住日期", ""),
                "check_out": props.get("退房日期", ""),
                "room_type": props.get("房型", ""),
                "room_category": props.get("房间等级", ""),
                "confirmation": props.get("confirmation #", ""),
            }
        )

    output = f"找到 {len(results)} 条酒店预订:\n\n"
    for r in results:
        output += f"【{r['hotel_name']}】\n"
        output += f"  入住: {r['check_in']}\n"
        output += f"  退房: {r['check_out']}\n"
        output += f"  房型: {r['room_type']}"
        if r["room_category"]:
            output += f" ({r['room_category']})"
        output += "\n"
        if r["address"]:
            output += f"  地址: {r['address']}\n"
        if r["confirmation"]:
            output += f"  确认号: {r['confirmation']}\n"
        output += "\n"

    return output
