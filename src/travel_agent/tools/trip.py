"""行程相关工具"""

from ..notion import NotionClient, DATABASES


def get_trip_info(trip_id: str) -> dict:
    """获取行程基本信息

    Args:
        trip_id: Notion 行程页面 ID

    Returns:
        行程信息字典
    """
    client = NotionClient()
    return client.get_page(trip_id)


def get_trip_events(trip_id: str) -> list[dict]:
    """获取行程关联的所有事件

    Args:
        trip_id: Notion 行程页面 ID

    Returns:
        事件列表
    """
    client = NotionClient()
    return client.query_pages(
        DATABASES["行程组件"],
        filter={"property": "行程", "relation": {"contains": trip_id}},
        sorts=[{"property": "日期", "direction": "ascending"}],
    )
