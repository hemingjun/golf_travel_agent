"""物流相关工具"""

from ..notion import NotionClient, DATABASES


def get_logistics_arrangements(trip_id: str) -> list[dict]:
    """获取行程关联的物流安排

    Args:
        trip_id: Notion 行程页面 ID

    Returns:
        物流安排列表
    """
    client = NotionClient()
    return client.query_pages(
        DATABASES["物流组件"],
        filter={"property": "关联行程", "relation": {"contains": trip_id}},
        sorts=[{"property": "日期", "direction": "ascending"}],
    )


def update_logistics(arrangement_id: str, data: dict) -> dict:
    """更新物流安排

    Args:
        arrangement_id: 物流记录 ID
        data: 要更新的数据

    Returns:
        更新后的物流信息
    """
    client = NotionClient()
    return client.update_page(arrangement_id, data, DATABASES["物流组件"])
