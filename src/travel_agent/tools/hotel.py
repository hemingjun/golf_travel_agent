"""酒店相关工具"""

from ..notion import get_client, DATABASES, SCHEMAS, transform_props
from ..debug import debug_print


def get_hotel_details(hotel_id: str) -> dict | None:
    """根据酒店 ID 获取酒店详细信息

    通过酒店页面 ID 查询酒店主数据库，获取完整酒店信息。

    Args:
        hotel_id: 酒店页面 ID

    Returns:
        酒店详情字典（英文 key），包含名称、地址、电话等；失败返回 None
    """
    try:
        client = get_client()
        page = client.get_page(hotel_id)
        if not page:
            return None

        props = page.get("properties", {})
        # 使用 transform_props 自动转换字段名（中文 → 英文）
        return transform_props(props, SCHEMAS["酒店"])
    except Exception as e:
        debug_print(f"[Hotel Tools] 获取酒店详情失败: {e}")
        return None


def get_hotel_bookings(trip_id: str, customer_id: str | None = None) -> list[dict]:
    """获取行程关联的酒店预订

    Args:
        trip_id: Notion 行程页面 ID
        customer_id: 客户 ID，如果提供则只返回该客户的预订

    Returns:
        酒店预订列表
    """
    client = get_client()

    # 构建过滤条件
    if customer_id:
        # 同时过滤行程和客户
        filter_condition = {
            "and": [
                {"property": "关联行程", "relation": {"contains": trip_id}},
                {"property": "客户", "relation": {"contains": customer_id}},
            ]
        }
    else:
        filter_condition = {"property": "关联行程", "relation": {"contains": trip_id}}

    return client.query_pages(
        DATABASES["酒店组件"],
        filter=filter_condition,
        sorts=[{"property": "入住日期", "direction": "ascending"}],
    )


def update_hotel_booking(booking_id: str, data: dict) -> dict:
    """更新酒店预订

    Args:
        booking_id: 预订记录 ID
        data: 要更新的数据

    Returns:
        更新后的预订信息
    """
    client = get_client()
    return client.update_page(booking_id, data, DATABASES["酒店组件"])
