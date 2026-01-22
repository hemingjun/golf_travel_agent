"""客户信息工具 + 认证函数"""

from langchain_core.tools import tool

from ..utils.debug import debug_print
from ..utils.notion import DATABASES, SCHEMAS, format_uuid, get_client, transform_props
from ..utils.notion.types import parse_rich_text


# ==================== 客户信息查询（使用 NotionClient TTL 缓存）====================


def get_customer_info(customer_id: str) -> dict | None:
    """获取客户基本信息（自动使用 NotionClient 的 TTL 缓存）

    Args:
        customer_id: 客户 Notion Page ID

    Returns:
        客户信息字典（英文 key），包含 name、country、handicap 等
    """
    client = get_client()
    try:
        page = client.get_page(customer_id)  # 自动使用 PAGE_CACHE (TTL 2分钟)
        props = page.get("properties", {})
        result = transform_props(props, SCHEMAS["客户"])
        result["id"] = page["id"]
        return result
    except Exception as e:
        debug_print(f"[Customer] 获取客户信息失败: {e}")
        return None


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
        return [cid.replace("-", "") for cid in customer_ids]
    except Exception as e:
        debug_print(f"[Customer] 获取行程客户列表失败: {e}")
        return []


def get_trip_customers_batch(trip_id: str) -> dict[str, dict]:
    """批量获取行程的所有客户信息（1 次 API 调用）

    Args:
        trip_id: 行程 Notion Page ID

    Returns:
        客户信息字典 {customer_id: customer_info}，使用英文 key
    """
    client = get_client()
    schema = SCHEMAS.get("客户", {})
    try:
        pages = client.query_pages(
            database_id=DATABASES["客户"],
            filter={"property": "参加的行程", "relation": {"contains": trip_id}},
        )
        result = {}
        for p in pages:
            props = p.get("properties", {})
            customer_info = transform_props(props, schema)
            customer_info["id"] = p["id"]
            result[p["id"]] = customer_info
        return result
    except Exception as e:
        debug_print(f"[Customer] 批量获取行程客户失败: {e}")
        return {}


def validate_customer_access(customer_id: str, trip_id: str) -> bool:
    """验证客户是否有权访问该行程

    Args:
        customer_id: 客户 Notion Page ID
        trip_id: 行程 Notion Page ID

    Returns:
        True 如果客户在该行程的客户列表中
    """
    trip_customers = get_trip_customers(trip_id)
    if not trip_customers:
        return False

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

    Args:
        full_name: 全名拼音 (格式: Last Name, First Name)
        birthday: 生日 (支持 YYYY-M-D 或 YYYY-MM-DD)
        trip_id: 行程 ID

    Returns:
        认证成功返回客户信息 dict（包含 id），失败返回 None
    """
    normalized_input = _normalize_name(full_name)
    normalized_birthday = _normalize_date(birthday)

    trip_customers = get_trip_customers(trip_id)
    if not trip_customers:
        debug_print(f"[Customer] 行程 {trip_id} 无关联客户")
        return None

    for customer_id in trip_customers:
        customer_info = get_customer_info(format_uuid(customer_id))
        if not customer_info:
            continue

        notion_name = customer_info.get("name", "")
        normalized_notion = _normalize_name(notion_name)

        if normalized_notion.startswith(normalized_input):
            customer_birthday = customer_info.get("birthday")
            if customer_birthday:
                birthday_str = (
                    customer_birthday.isoformat()
                    if hasattr(customer_birthday, "isoformat")
                    else str(customer_birthday)
                )
                if birthday_str == normalized_birthday:
                    debug_print(f"[Customer] 认证成功: {notion_name}")
                    return customer_info

    debug_print(f"[Customer] 未找到匹配客户: {full_name}, {birthday}")
    return None


def authenticate_customer_cached(
    full_name: str, birthday: str, customers_cache: dict
) -> dict | None:
    """从缓存中认证客户（无 API 调用，毫秒级响应）

    Args:
        full_name: 全名拼音 (格式: Last Name, First Name)
        birthday: 生日 (支持 YYYY-M-D 或 YYYY-MM-DD)
        customers_cache: 预加载的客户信息字典 {customer_id: customer_info}

    Returns:
        认证成功返回客户信息 dict，失败返回 None
    """
    normalized_input = _normalize_name(full_name)
    normalized_birthday = _normalize_date(birthday)

    for customer_info in customers_cache.values():
        if not customer_info:
            continue

        notion_name = customer_info.get("name", "")
        normalized_notion = _normalize_name(notion_name)

        if normalized_notion.startswith(normalized_input):
            customer_birthday = customer_info.get("birthday")
            if customer_birthday:
                birthday_str = (
                    customer_birthday.isoformat()
                    if hasattr(customer_birthday, "isoformat")
                    else str(customer_birthday)
                )
                if birthday_str == normalized_birthday:
                    debug_print(f"[Customer] 缓存认证成功: {notion_name}")
                    return customer_info

    debug_print(f"[Customer] 缓存中未找到匹配客户: {full_name}, {birthday}")
    return None


# ==================== 客户工具 ====================


def create_customer_tool(customer_id: str | None):
    """创建客户档案查询工具"""

    @tool
    def query_customer() -> str:
        """查询客户档案信息

        获取当前客户的个人信息。

        返回信息包括：
        - 姓名、国籍
        - 高尔夫差点 (Handicap)
        - 饮食偏好
        - 服务需求
        - 会员等级

        适用场景：
        - "我的差点是多少？"
        - "有什么饮食禁忌？"
        - "我的会员等级？"

        注意：
        - 此工具仅在客户模式下可用
        - 管理员模式下调用会返回错误
        """
        if not customer_id:
            return "错误：当前为管理员模式，无法查询客户档案。请指定具体客户。"

        client = get_client()
        try:
            page = client.get_page(customer_id)
            props = page.get("properties", {})
            info = transform_props(props, SCHEMAS.get("客户", {}))

            # 解析国籍（relation → 名称）
            country_ids = info.get("country", [])
            country_name = ""
            if country_ids:
                try:
                    country_page = client.get_page(country_ids[0])
                    country_props = country_page.get("properties", {})
                    for prop in country_props.values():
                        if prop.get("type") == "title":
                            country_name = parse_rich_text(prop.get("title", []))
                            break
                except Exception:
                    pass

            output = "【客户档案】\n"
            output += f"姓名: {info.get('name', '未知')}\n"
            if country_name:
                output += f"国籍: {country_name}\n"
            output += f"差点: {info.get('handicap', '未知')}\n"

            dietary = info.get("dietary_preferences", "")
            if dietary:
                output += f"饮食偏好: {dietary}\n"

            service = info.get("service_requirements", "")
            if service:
                output += f"服务需求: {service}\n"

            membership = info.get("membership_type", [])
            if membership:
                output += f"与公司关系: {', '.join(membership)}\n"

            return output
        except Exception as e:
            return f"获取客户信息失败: {e}"

    return query_customer


def create_update_dietary_preferences_tool(customer_id: str | None):
    """创建更新客户饮食偏好工具"""

    @tool
    def update_dietary_preferences(preference: str) -> str:
        """记录客户的饮食偏好或禁忌

        当客户告知饮食相关的偏好、过敏或禁忌时，使用此工具记录。

        Args:
            preference: 饮食偏好描述

        适用场景（饮食相关）：
        - "我对海鲜过敏"
        - "我吃素 / 我是素食者"
        - "不能吃猪肉"
        - "对花生过敏"
        - "乳糖不耐受"
        - "清真饮食"

        注意：
        - 仅用于饮食相关需求，其他服务需求请使用 update_service_requirements
        - 新偏好会追加到现有记录
        """
        if not customer_id:
            return "错误：当前为管理员模式，无法更新。"

        client = get_client()
        try:
            page = client.get_page(customer_id)
            props = page.get("properties", {})
            info = transform_props(props, SCHEMAS.get("客户", {}))
            existing = info.get("dietary_preferences", "")

            if existing:
                new_preferences = f"{existing}\n- {preference}"
            else:
                new_preferences = f"- {preference}"

            client.update_page(
                page_id=customer_id,
                data={"饮食习惯": new_preferences},
            )

            debug_print(f"[Customer] 已记录饮食偏好: {preference}")
            return f"已记录您的饮食偏好：{preference}"
        except Exception as e:
            debug_print(f"[Customer] 更新饮食偏好失败: {e}")
            return f"记录失败: {e}"

    return update_dietary_preferences


def create_update_service_requirements_tool(customer_id: str | None):
    """创建更新客户服务需求工具"""

    @tool
    def update_service_requirements(requirements: str) -> str:
        """记录客户的服务需求（非饮食类）

        当客户告知特殊服务需求时使用此工具。饮食相关请使用 update_dietary_preferences。

        Args:
            requirements: 服务需求描述

        适用场景（非饮食类服务）：
        - "我需要轮椅服务"
        - "希望安排海景房"
        - "每天早上 6 点叫醒服务"
        - "需要婴儿床"
        - "希望安排中文导游"

        注意：
        - 饮食相关（过敏、忌口、素食等）请使用 update_dietary_preferences
        - 新需求会追加到现有记录
        """
        if not customer_id:
            return "错误：当前为管理员模式，无法更新客户需求。"

        client = get_client()
        try:
            # 获取现有需求
            page = client.get_page(customer_id)
            props = page.get("properties", {})
            info = transform_props(props, SCHEMAS.get("客户", {}))
            existing = info.get("service_requirements", "")

            # 追加新需求
            if existing:
                new_requirements = f"{existing}\n- {requirements}"
            else:
                new_requirements = f"- {requirements}"

            # 更新到 Notion
            client.update_page(
                page_id=customer_id,
                data={"服务需求": new_requirements},
            )

            debug_print(f"[Customer] 已记录服务需求: {requirements}")
            return f"已记录您的需求：{requirements}"
        except Exception as e:
            debug_print(f"[Customer] 更新服务需求失败: {e}")
            return f"记录需求失败: {e}"

    return update_service_requirements


def create_update_handicap_tool(customer_id: str | None):
    """创建更新客户差点工具"""

    @tool
    def update_handicap(handicap: float) -> str:
        """更新客户的高尔夫差点

        当客户告知自己的差点变化时，使用此工具更新记录。

        Args:
            handicap: 新的差点数值（0-54 之间的数字）

        适用场景：
        - "我的差点现在是 18"
        - "最近打得不错，差点降到 12 了"
        - "帮我更新差点为 25"

        注意：
        - 差点范围通常在 0-54 之间
        - 数值越低表示水平越高
        """
        if not customer_id:
            return "错误：当前为管理员模式，无法更新。"

        if handicap < 0 or handicap > 54:
            return "错误：差点数值应在 0-54 之间"

        client = get_client()
        try:
            client.update_page(
                page_id=customer_id,
                data={"差点": handicap},
            )

            debug_print(f"[Customer] 已更新差点: {handicap}")
            return f"已更新您的差点为：{handicap}"
        except Exception as e:
            debug_print(f"[Customer] 更新差点失败: {e}")
            return f"更新失败: {e}"

    return update_handicap
