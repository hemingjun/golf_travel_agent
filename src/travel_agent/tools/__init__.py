"""统一工具库

导出 create_all_tools 函数，供 graph.py 使用。
"""

from .customer import (
    authenticate_customer,
    authenticate_customer_cached,
    create_customer_tool,
    create_update_dietary_preferences_tool,
    create_update_handicap_tool,
    create_update_service_requirements_tool,
    get_customer_info,
    get_trip_customers_batch,
    validate_customer_access,
)
from .golf import create_golf_tool
from .hotel import create_hotel_tool
from .itinerary import create_itinerary_tool
from .logistics import create_logistics_tool
from .search import create_search_tool
from .weather import create_weather_tool


def create_all_tools(trip_id: str, customer_id: str | None = None):
    """创建统一工具集

    Args:
        trip_id: 行程 ID
        customer_id: 客户 ID（可选，用于权限过滤）

    Returns:
        工具函数列表，供 ReAct Agent 使用
    """
    return [
        create_golf_tool(trip_id),
        create_hotel_tool(trip_id, customer_id),
        create_itinerary_tool(trip_id),
        create_logistics_tool(trip_id),
        create_customer_tool(customer_id),
        create_update_dietary_preferences_tool(customer_id),
        create_update_handicap_tool(customer_id),
        create_update_service_requirements_tool(customer_id),
        create_weather_tool(),
        create_search_tool(),
    ]


__all__ = [
    "create_all_tools",
    "get_customer_info",
    "validate_customer_access",
    "authenticate_customer",
    "authenticate_customer_cached",
    "get_trip_customers_batch",
]
