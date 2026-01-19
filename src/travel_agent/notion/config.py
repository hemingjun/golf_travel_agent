"""Notion 数据库配置"""

import os


def normalize_id(notion_id: str) -> str:
    """标准化 Notion ID - 统一去掉连字符（用于内部比较）"""
    return notion_id.replace("-", "")


def format_uuid(id_str: str) -> str:
    """将 ID 格式化为标准 UUID 格式（带连字符）

    Notion API 需要 8-4-4-4-12 格式的 UUID
    """
    clean_id = id_str.replace("-", "")
    if len(clean_id) != 32:
        return id_str
    return f"{clean_id[:8]}-{clean_id[8:12]}-{clean_id[12:16]}-{clean_id[16:20]}-{clean_id[20:]}"


def _get_db_id(env_key: str, name: str) -> str:
    """从环境变量获取数据库 ID（转为 UUID 格式供 API 使用）"""
    db_id = os.getenv(env_key)
    if not db_id:
        raise ValueError(f"未配置 {env_key}，请在 .env 中设置 {name} 数据库 ID")
    return format_uuid(db_id)


def get_databases() -> dict[str, str]:
    """获取数据库 ID 映射（延迟加载）"""
    return {
        "行程组件": _get_db_id("NOTION_DB_ITINERARY", "行程组件"),
        "高尔夫组件": _get_db_id("NOTION_DB_GOLF", "高尔夫组件"),
        "酒店组件": _get_db_id("NOTION_DB_HOTEL", "酒店组件"),
        "物流组件": _get_db_id("NOTION_DB_LOGISTIC", "物流组件"),
        "客户": _get_db_id("NOTION_DB_CUSTOMER", "客户"),
    }


# 延迟初始化的数据库映射
_databases_cache: dict[str, str] | None = None


def _get_databases() -> dict[str, str]:
    global _databases_cache
    if _databases_cache is None:
        _databases_cache = get_databases()
    return _databases_cache


class _DatabasesProxy:
    """代理对象，延迟加载数据库 ID"""
    def __getitem__(self, key: str) -> str:
        return _get_databases()[key]

    def get(self, key: str, default=None):
        return _get_databases().get(key, default)

    def items(self):
        return _get_databases().items()

    def values(self):
        return _get_databases().values()

    def keys(self):
        return _get_databases().keys()


DATABASES = _DatabasesProxy()

# 数据库 Schema 定义（基于实际数据库结构）
# 格式: {"中文字段名": {"type": "notion类型", "key": "英文业务key"}}
# key 用于统一的字段映射，type 用于 Notion API 交互
SCHEMAS = {
    # 行程组件 - 实际名称: 行程数据库_行程事件
    "行程组件": {
        "标题": {"type": "title", "key": "event_title"},
        "日期": {"type": "date", "key": "event_date"},
        "事件类型": {"type": "select", "key": "event_type"},
        "事件内容": {"type": "rich_text", "key": "event_content"},
        "行程": {"type": "relation", "key": "trip_id"},
        "球场": {"type": "relation", "key": "course_id"},
        "酒店": {"type": "relation", "key": "hotel_id"},
        "Teetime": {"type": "rich_text", "key": "tee_time"},
        "行程时长": {"type": "rich_text", "key": "duration"},
        "天气": {"type": "rich_text", "key": "weather"},
        "是否提醒": {"type": "checkbox", "key": "reminder_enabled"},
        "提醒状态": {"type": "select", "key": "reminder_status"},
    },
    # 高尔夫组件 - 实际名称: 行程数据库_高尔夫组件
    "高尔夫组件": {
        "名称": {"type": "title", "key": "name"},
        "PlayDate": {"type": "date", "key": "play_date"},
        "Teetime": {"type": "rich_text", "key": "tee_time"},
        "关联行程": {"type": "relation", "key": "trip_id"},
        "关联球场": {"type": "relation", "key": "course_id"},
        "球手": {"type": "relation", "key": "players"},
        "Notes": {"type": "rich_text", "key": "notes"},
        "Caddie": {"type": "checkbox", "key": "caddie"},
        "Buggie": {"type": "checkbox", "key": "buggy"},
        # rollup 字段（只读）
        "中文名": {"type": "rollup", "key": "course_name_cn", "readonly": True},
        "地址": {"type": "rollup", "key": "course_address", "readonly": True},
        "电话": {"type": "rollup", "key": "course_phone", "readonly": True},
    },
    # 酒店组件 - 实际名称: 行程数据库_酒店组件
    "酒店组件": {
        "名称": {"type": "title", "key": "name"},
        "入住日期": {"type": "date", "key": "check_in"},
        "退房日期": {"type": "date", "key": "check_out"},
        "关联行程": {"type": "relation", "key": "trip_id"},
        "酒店": {"type": "relation", "key": "hotel_id"},
        "客户": {"type": "relation", "key": "customer_id"},
        "房型": {"type": "select", "key": "room_type"},
        "房间等级": {"type": "select", "key": "room_category"},
        "景观": {"type": "select", "key": "view"},
        "备注": {"type": "rich_text", "key": "notes"},
        "confirmation #": {"type": "rich_text", "key": "confirmation_number"},
    },
    # 酒店主数据库 - 资料数据库_酒店
    "酒店": {
        "英文名": {"type": "title", "key": "name_en"},
        "中文名": {"type": "rich_text", "key": "name_cn"},
        "地址": {"type": "rich_text", "key": "address"},
        "电话": {"type": "phone_number", "key": "phone"},
        "早餐信息": {"type": "rich_text", "key": "breakfast"},
        "入住时间": {"type": "rich_text", "key": "check_in_time"},
        "退房时间": {"type": "rich_text", "key": "check_out_time"},
        "星级": {"type": "select", "key": "star_rating"},
        "官网": {"type": "url", "key": "website"},
        "入住须知": {"type": "rich_text", "key": "check_in_notes"},
        "酒店简介": {"type": "rich_text", "key": "description"},
        "酒店备注": {"type": "rich_text", "key": "remarks"},
    },
    # 物流组件 - 实际名称: 行程数据库_物流组件
    "物流组件": {
        "名称": {"type": "title", "key": "name"},
        "日期": {"type": "date", "key": "transport_date"},
        "出发时间": {"type": "rich_text", "key": "departure_time"},
        "目的地": {"type": "rich_text", "key": "destination"},
        "车型": {"type": "rich_text", "key": "vehicle_type"},
        "人数": {"type": "rich_text", "key": "passenger_count"},
        "行程时长(分钟)": {"type": "number", "key": "duration_minutes"},
        "关联行程": {"type": "relation", "key": "trip_id"},
        "客户": {"type": "relation", "key": "customer_id"},
        "备注": {"type": "rich_text", "key": "notes"},
    },
    # 客户 - 实际名称: 人员数据库_客户
    "客户": {
        "Name": {"type": "title", "key": "name"},
        "国家(必填)": {"type": "relation", "key": "country"},
        "差点": {"type": "number", "key": "handicap"},
        "饮食习惯": {"type": "rich_text", "key": "dietary_preferences"},
        "服务需求": {"type": "rich_text", "key": "service_requirements"},
        "亲友": {"type": "relation", "key": "relatives"},
        "参加的行程": {"type": "relation", "key": "trips"},
        "会员类型(必填)": {"type": "multi_select", "key": "membership_type"},
        "备注": {"type": "rich_text", "key": "notes"},
        # formula 字段（只读）
        "page_id": {"type": "formula", "key": "page_id", "readonly": True},
    },
}


def get_field_type(db_name: str, field_name: str) -> str | None:
    """获取字段的 Notion 类型"""
    schema = SCHEMAS.get(db_name, {})
    field_def = schema.get(field_name)
    if isinstance(field_def, dict):
        return field_def.get("type")
    return field_def  # 兼容旧格式


def get_field_key(db_name: str, field_name: str) -> str:
    """获取字段的英文 key，如果没有定义则返回原字段名"""
    schema = SCHEMAS.get(db_name, {})
    field_def = schema.get(field_name)
    if isinstance(field_def, dict):
        return field_def.get("key", field_name)
    return field_name

def _build_writable_fields() -> dict[str, list[str]]:
    """从 SCHEMAS 自动生成可写字段列表（排除 readonly 字段）"""
    result = {}
    for db_name, schema in SCHEMAS.items():
        writable = []
        for field_name, field_def in schema.items():
            if isinstance(field_def, dict):
                if not field_def.get("readonly"):
                    writable.append(field_name)
            else:
                writable.append(field_name)
        if writable:
            result[db_name] = writable
    return result


# 可写字段（自动从 SCHEMAS 生成，排除 rollup/formula 等只读字段）
WRITABLE_FIELDS = _build_writable_fields()
