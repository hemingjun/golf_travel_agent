"""客户相关工具"""

from ..debug import debug_print
from ..notion import NotionClient, DATABASES, SCHEMAS, transform_props


def get_customer_info(customer_id: str) -> dict | None:
    """获取客户基本信息

    Args:
        customer_id: 客户 Notion Page ID

    Returns:
        客户信息字典（英文 key），包含 name、country、handicap 等
    """
    client = NotionClient()
    try:
        page = client.get_page(customer_id)
        props = page.get("properties", {})
        # 使用 transform_props 自动转换字段名（中文 → 英文）
        result = transform_props(props, SCHEMAS["客户"])
        result["id"] = page["id"]
        return result
    except Exception as e:
        debug_print(f"[ERROR] 获取客户信息失败: {e}")
        return None


def get_customer_relatives(customer_id: str) -> list[dict]:
    """获取客户的亲友信息

    【安全】只能获取该客户 relation 中关联的亲友

    Args:
        customer_id: 客户 Notion Page ID

    Returns:
        亲友列表（英文 key，只包含基本信息）
    """
    # 先获取客户信息，得到亲友 ID 列表
    customer = get_customer_info(customer_id)
    if not customer:
        return []

    # 使用新的英文 key
    relative_ids = customer.get("relatives", [])
    if not relative_ids:
        return []

    client = NotionClient()
    relatives = []

    for rel_id in relative_ids:
        try:
            page = client.get_page(rel_id)
            props = page.get("properties", {})
            # 使用 transform_props 转换
            rel_info = transform_props(props, SCHEMAS["客户"])
            rel_info["id"] = page["id"]
            # 只保留基本信息
            relatives.append({
                "id": rel_info["id"],
                "name": rel_info.get("name", ""),
                "handicap": rel_info.get("handicap"),
            })
        except Exception as e:
            debug_print(f"[WARN] 获取亲友信息失败 {rel_id}: {e}")

    return relatives


def get_customer_trips(customer_id: str) -> list[dict]:
    """获取客户参加的行程

    【安全】只能获取该客户 relation 中关联的行程

    Args:
        customer_id: 客户 Notion Page ID

    Returns:
        行程列表（英文 key）
    """
    customer = get_customer_info(customer_id)
    if not customer:
        return []

    # 使用新的英文 key
    trip_ids = customer.get("trips", [])
    if not trip_ids:
        return []

    client = NotionClient()
    trips = []

    for trip_id in trip_ids:
        try:
            page = client.get_page(trip_id)
            props = page.get("properties", {})
            trips.append({
                "id": page["id"],
                "name": props.get("Name", "") or props.get("名称", ""),
                "date": props.get("项目日期"),
            })
        except Exception as e:
            debug_print(f"[WARN] 获取行程信息失败 {trip_id}: {e}")

    return trips


def get_trip_customers(trip_id: str) -> list[str]:
    """获取行程关联的客户 ID 列表

    Args:
        trip_id: 行程 Notion Page ID

    Returns:
        客户 ID 列表（标准化后的，不带连字符）
    """
    client = NotionClient()
    try:
        page = client.get_page(trip_id)
        props = page.get("properties", {})
        customer_ids = props.get("客户", [])
        # 标准化 ID（去掉连字符）
        return [cid.replace("-", "") for cid in customer_ids]
    except Exception as e:
        debug_print(f"[ERROR] 获取行程客户列表失败: {e}")
        return []


def validate_customer_access(customer_id: str, trip_id: str) -> bool:
    """验证客户是否有权访问该行程

    【安全】从行程端验证，确保客户在行程的客户列表中

    Args:
        customer_id: 客户 Notion Page ID
        trip_id: 行程 Notion Page ID

    Returns:
        True 如果客户在该行程的客户列表中
    """
    # 从行程获取客户列表
    trip_customers = get_trip_customers(trip_id)
    if not trip_customers:
        return False

    # 标准化比较（去掉连字符）
    normalized_customer_id = customer_id.replace("-", "")
    return normalized_customer_id in trip_customers
