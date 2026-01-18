"""客户相关工具"""

from ..config import debug_print
from ..notion import NotionClient, DATABASES


def get_customer_info(customer_id: str) -> dict | None:
    """获取客户基本信息

    Args:
        customer_id: 客户 Notion Page ID

    Returns:
        客户信息字典，包含全名、国家、差点、饮食习惯、服务需求等
    """
    client = NotionClient()
    try:
        page = client.get_page(customer_id)
        props = page.get("properties", {})
        return {
            "id": page["id"],
            "全名": props.get("Name", ""),
            "国家": props.get("国家(必填)", []),
            "差点": props.get("差点"),
            "饮食习惯": props.get("饮食习惯", ""),
            "服务需求": props.get("服务需求", ""),
            "会员类型": props.get("会员类型(必填)", []),
            "备注": props.get("备注", ""),
            "亲友_ids": props.get("亲友", []),
            "参加的行程_ids": props.get("参加的行程", []),
        }
    except Exception as e:
        debug_print(f"[ERROR] 获取客户信息失败: {e}")
        return None


def get_customer_relatives(customer_id: str) -> list[dict]:
    """获取客户的亲友信息

    【安全】只能获取该客户 relation 中关联的亲友

    Args:
        customer_id: 客户 Notion Page ID

    Returns:
        亲友列表（只包含基本信息）
    """
    # 先获取客户信息，得到亲友 ID 列表
    customer = get_customer_info(customer_id)
    if not customer:
        return []

    relative_ids = customer.get("亲友_ids", [])
    if not relative_ids:
        return []

    client = NotionClient()
    relatives = []

    for rel_id in relative_ids:
        try:
            page = client.get_page(rel_id)
            props = page.get("properties", {})
            relatives.append({
                "id": page["id"],
                "全名": props.get("Name", ""),
                "差点": props.get("差点"),
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
        行程列表
    """
    customer = get_customer_info(customer_id)
    if not customer:
        return []

    trip_ids = customer.get("参加的行程_ids", [])
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
                "名称": props.get("Name", "") or props.get("名称", ""),
                "项目日期": props.get("项目日期"),
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
