"""统一工具库

工具从 RunnableConfig 动态获取 trip_id/customer_id，无需构建时绑定。
"""

from .customer import (
    authenticate_customer,
    authenticate_customer_cached,
    get_customer_info,
    get_trip_customers_batch,
    query_customer,
    update_dietary_preferences,
    update_handicap,
    update_service_requirements,
    validate_customer_access,
)
from .golf import query_golf_bookings
from .hotel import query_hotel_bookings
from .itinerary import query_itinerary
from .logistics import query_logistics
from .search import search_web
from .weather import query_weather


# 所有工具列表 - 工具从 config["configurable"] 读取 trip_id/customer_id
ALL_TOOLS = [
    query_golf_bookings,
    query_hotel_bookings,
    query_itinerary,
    query_logistics,
    query_customer,
    update_dietary_preferences,
    update_handicap,
    update_service_requirements,
    query_weather,
    search_web,
]


def get_all_tools():
    """获取所有工具

    工具在运行时从 config["configurable"] 读取 trip_id/customer_id，
    无需在此传递参数。

    Returns:
        工具函数列表，供 ReAct Agent 使用
    """
    return ALL_TOOLS


__all__ = [
    "get_all_tools",
    "ALL_TOOLS",
    # 辅助函数（用于认证和验证）
    "get_customer_info",
    "validate_customer_access",
    "authenticate_customer",
    "authenticate_customer_cached",
    "get_trip_customers_batch",
]
