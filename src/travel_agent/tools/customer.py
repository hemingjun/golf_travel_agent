"""客户相关工具"""

from ..debug import debug_print
from ..notion import get_client, SCHEMAS, transform_props, format_uuid


# ==================== 客户信息缓存 ====================

_customer_cache: dict[str, dict] = {}


def clear_customer_cache() -> None:
    """清除客户信息缓存"""
    _customer_cache.clear()


def get_customer_info(customer_id: str, use_cache: bool = True) -> dict | None:
    """获取客户基本信息（支持缓存）

    Args:
        customer_id: 客户 Notion Page ID
        use_cache: 是否使用缓存（默认 True）

    Returns:
        客户信息字典（英文 key），包含 name、country、handicap 等
    """
    # 标准化 ID 用于缓存 key
    cache_key = customer_id.replace("-", "")

    # 检查缓存
    if use_cache and cache_key in _customer_cache:
        return _customer_cache[cache_key]

    client = get_client()
    try:
        page = client.get_page(customer_id)
        props = page.get("properties", {})
        # 使用 transform_props 自动转换字段名（中文 → 英文）
        result = transform_props(props, SCHEMAS["客户"])
        result["id"] = page["id"]

        # 写入缓存
        _customer_cache[cache_key] = result
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

    client = get_client()
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

    client = get_client()
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
    client = get_client()
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


def _normalize_name(name: str) -> str:
    """标准化姓名 - 去空格、转小写，保留逗号"""
    return name.replace(" ", "").lower()


def _normalize_date(date_str: str) -> str:
    """标准化日期格式 - 补零 (1995-1-12 → 1995-01-12)"""
    parts = date_str.split("-")
    if len(parts) == 3:
        year, month, day = parts
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    return date_str


def authenticate_customer(full_name: str, birthday: str, trip_id: str) -> dict | None:
    """通过全名+生日认证客户（智能格式兼容）

    支持格式兼容：
    - 姓名: "Yan, BinZhe" / "Yan, Bin Zhe" / "yan, binzhe" 均可匹配 "Yan, BinZhe 老言"
    - 生日: "1995-1-12" / "1995-01-12" 均可

    Args:
        full_name: 全名拼音 (格式: Last Name, First Name)
        birthday: 生日 (支持 YYYY-M-D 或 YYYY-MM-DD)
        trip_id: 行程 ID

    Returns:
        认证成功返回客户信息 dict（包含 id），失败返回 None
    """
    # 1. 标准化输入
    normalized_input = _normalize_name(full_name)
    normalized_birthday = _normalize_date(birthday)

    # 2. 获取该行程的所有客户 ID
    trip_customers = get_trip_customers(trip_id)
    if not trip_customers:
        debug_print(f"[INFO] 行程 {trip_id} 无关联客户")
        return None

    # 3. 遍历客户，智能匹配姓名和生日
    for customer_id in trip_customers:
        # 转换为 UUID 格式（Notion API 需要带连字符的格式）
        customer_info = get_customer_info(format_uuid(customer_id))
        if not customer_info:
            continue

        # 标准化 Notion 中的姓名并比较
        notion_name = customer_info.get("name", "")
        normalized_notion = _normalize_name(notion_name)

        # startsWith 匹配（Notion 存储: "Yan, BinZhe 老言"）
        if normalized_notion.startswith(normalized_input):
            # 验证生日（注意：Notion 返回的是 date 对象，需要转为字符串）
            customer_birthday = customer_info.get("birthday")
            if customer_birthday:
                # 转换为 ISO 格式字符串进行比较
                birthday_str = (
                    customer_birthday.isoformat()
                    if hasattr(customer_birthday, "isoformat")
                    else str(customer_birthday)
                )
                if birthday_str == normalized_birthday:
                    debug_print(f"[INFO] 认证成功: {notion_name}")
                    return customer_info

    debug_print(f"[INFO] 未找到匹配客户: {full_name}, {birthday}")
    return None
