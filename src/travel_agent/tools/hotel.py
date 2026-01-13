"""酒店相关工具"""

from ..notion import NotionClient, DATABASES


def get_hotel_bookings(trip_id: str) -> list[dict]:
    """获取行程关联的酒店预订

    Args:
        trip_id: Notion 行程页面 ID

    Returns:
        酒店预订列表
    """
    client = NotionClient()
    return client.query_pages(
        DATABASES["酒店组件"],
        filter={"property": "关联行程", "relation": {"contains": trip_id}},
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
    client = NotionClient()
    return client.update_page(booking_id, data, DATABASES["酒店组件"])
