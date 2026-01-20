"""高尔夫相关工具"""

from ..notion import get_client, DATABASES


def get_golf_bookings(trip_id: str) -> list[dict]:
    """获取行程关联的高尔夫预订

    Args:
        trip_id: Notion 行程页面 ID

    Returns:
        高尔夫预订列表
    """
    client = get_client()
    return client.query_pages(
        DATABASES["高尔夫组件"],
        filter={"property": "关联行程", "relation": {"contains": trip_id}},
        sorts=[{"property": "PlayDate", "direction": "ascending"}],
    )


def update_golf_booking(booking_id: str, data: dict) -> dict:
    """更新高尔夫预订

    Args:
        booking_id: 预订记录 ID
        data: 要更新的数据

    Returns:
        更新后的预订信息
    """
    client = get_client()
    return client.update_page(booking_id, data, DATABASES["高尔夫组件"])
