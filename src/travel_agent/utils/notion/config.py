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
# 格式: {"中文字段名": {"type": "notion类型", "key": "英文业务key", "semantic": "业务语义"}}
# - __meta__: 实体级元信息（entity_key, agent, description, business_context）
# - type: Notion API 字段类型
# - key: 统一的英文业务标识
# - semantic: 字段的业务含义说明
# - relation_target: relation 字段指向的目标实体
# - cardinality: 关系基数（one/many）
SCHEMAS = {
    # ==================== 行程组件 ====================
    "行程组件": {
        "__meta__": {
            "entity_key": "itinerary",
            "agent": "itinerary_agent",
            "description": "行程中的单个日程事件",
            "business_context": "时间线视图的基本单位，只记录事件概要和关联的组件",
        },
        "标题": {"type": "title", "key": "event_title", "semantic": "事件的显示标题"},
        "日期": {"type": "date", "key": "event_date", "semantic": "事件发生的日期"},
        "事件类型": {
            "type": "select",
            "key": "event_type",
            "semantic": "事件分类（航班/酒店/球场/餐饮/其他）",
        },
        "事件内容": {
            "type": "rich_text",
            "key": "event_content",
            "semantic": "事件的详细描述",
        },
        "行程": {
            "type": "relation",
            "key": "trip_id",
            "semantic": "所属的旅行行程",
            "relation_target": "行程",
            "cardinality": "one",
        },
        "球场": {
            "type": "relation",
            "key": "course_id",
            "semantic": "关联的球场（仅打球事件）",
            "relation_target": "球场",
            "cardinality": "one",
        },
        "酒店": {
            "type": "relation",
            "key": "hotel_id",
            "semantic": "关联的酒店（当天入住的酒店）",
            "relation_target": "酒店",
            "cardinality": "one",
        },
    },
    # ==================== 高尔夫组件 ====================
    "高尔夫组件": {
        "__meta__": {
            "entity_key": "golf",
            "agent": "golf_agent",
            "description": "单组高尔夫Teetime预订的完整信息",
            "business_context": "一条记录 = 一次打球Teetime。",
        },
        "名称": {"type": "title", "key": "name", "semantic": "预订的显示名称"},
        "PlayDate": {"type": "date", "key": "play_date", "semantic": "打球日期"},
        "Teetime": {
            "type": "rich_text",
            "key": "tee_time",
            "semantic": "开球时间，格式 HH:MM",
        },
        "关联行程": {
            "type": "relation",
            "key": "trip_id",
            "semantic": "所属的旅行行程",
            "relation_target": "行程",
            "cardinality": "one",
        },
        "关联球场": {
            "type": "relation",
            "key": "course_id",
            "semantic": "预订的球场",
            "relation_target": "球场",
            "cardinality": "one",
        },
        "球手": {
            "type": "relation",
            "key": "players",
            "semantic": "参与本次Teetime的客户列表",
            "relation_target": "客户",
            "cardinality": "many",
        },
        "Notes": {"type": "rich_text", "key": "notes", "semantic": "预订备注"},
        "Caddie": {"type": "checkbox", "key": "caddie", "semantic": "是否需要球童"},
        "Buggie": {"type": "checkbox", "key": "buggy", "semantic": "是否需要球车"},
        # rollup 字段（只读，从关联球场自动获取）
        "中文名": {
            "type": "rollup",
            "key": "course_name_cn",
            "readonly": True,
            "semantic": "球场中文名（自动关联）",
        },
        "地址": {
            "type": "rollup",
            "key": "course_address",
            "readonly": True,
            "semantic": "球场地址（自动关联）",
        },
        "电话": {
            "type": "rollup",
            "key": "course_phone",
            "readonly": True,
            "semantic": "球场电话（自动关联）",
        },
    },
    # ==================== 酒店组件 ====================
    "酒店组件": {
        "__meta__": {
            "entity_key": "hotel_booking",
            "agent": "hotel_agent",
            "description": "单次酒店单个房间预订记录",
            "business_context": "记录入住日期、房型、客户。酒店详情（名称、地址、电话）需通过 hotel_id 关联查询酒店主数据。",
        },
        "名称": {"type": "title", "key": "name", "semantic": "预订的显示名称"},
        "入住日期": {"type": "date", "key": "check_in", "semantic": "入住日期"},
        "退房日期": {"type": "date", "key": "check_out", "semantic": "退房日期"},
        "关联行程": {
            "type": "relation",
            "key": "trip_id",
            "semantic": "所属的旅行行程",
            "relation_target": "行程",
            "cardinality": "one",
        },
        "酒店": {
            "type": "relation",
            "key": "hotel_id",
            "semantic": "预订的酒店（需二次查询获取详情）",
            "relation_target": "酒店",
            "cardinality": "one",
        },
        "客户": {
            "type": "relation",
            "key": "customer_id",
            "semantic": "入住的客户列表",
            "relation_target": "客户",
            "cardinality": "many",
        },
        "房型": {
            "type": "select",
            "key": "room_type",
            "semantic": "房间类型(Single Room(1 King)/Double Room(1 King)/Double Room(2 Queen)/Suit/Villa/Aaprtment))",
        },
        "房间等级": {
            "type": "select",
            "key": "room_category",
            "semantic": "房间等级(Economy Room/Standard Room/Superior Deluxe Room/Executive Room)",
        },
        "景观": {
            "type": "select",
            "key": "view",
            "semantic": "房间景观(City View/Ocean View/Garden View)",
        },
        "备注": {"type": "rich_text", "key": "notes", "semantic": "预订备注"},
        "confirmation #": {
            "type": "rich_text",
            "key": "confirmation_number",
            "semantic": "确认号",
        },
    },
    # ==================== 酒店主数据库 ====================
    "酒店": {
        "__meta__": {
            "entity_key": "hotel",
            "agent": "hotel_agent",
            "description": "酒店主数据（非预订记录）",
            "business_context": "酒店的基本信息库，包含名称、地址、联系方式、星级等。通过酒店组件的 hotel_id 关联。",
        },
        "英文名": {"type": "title", "key": "name_en", "semantic": "酒店英文名称"},
        "中文名": {"type": "rich_text", "key": "name_cn", "semantic": "酒店中文名称"},
        "地址": {"type": "rich_text", "key": "address", "semantic": "酒店详细地址"},
        "电话": {"type": "phone_number", "key": "phone", "semantic": "酒店联系电话"},
        "早餐信息": {
            "type": "rich_text",
            "key": "breakfast",
            "semantic": "早餐安排说明",
        },
        "入住时间": {
            "type": "rich_text",
            "key": "check_in_time",
            "semantic": "最早入住时间",
        },
        "退房时间": {
            "type": "rich_text",
            "key": "check_out_time",
            "semantic": "最晚退房时间",
        },
        "星级": {"type": "select", "key": "star_rating", "semantic": "酒店星级"},
        "官网": {"type": "url", "key": "website", "semantic": "酒店官网"},
        "入住须知": {
            "type": "rich_text",
            "key": "check_in_notes",
            "semantic": "入住注意事项",
        },
        "酒店简介": {"type": "rich_text", "key": "description", "semantic": "酒店介绍"},
        "酒店备注": {"type": "rich_text", "key": "remarks", "semantic": "其他备注"},
    },
    # ==================== 物流组件 ====================
    "物流组件": {
        "__meta__": {
            "entity_key": "logistics",
            "agent": "logistics_agent",
            "description": "单次接送/交通安排",
            "business_context": "记录出发时间、目的地、车型、乘客。一条记录 = 一次接送任务。",
        },
        "名称": {"type": "title", "key": "name", "semantic": "接送任务的显示名称"},
        "日期": {"type": "date", "key": "transport_date", "semantic": "接送日期"},
        "出发时间": {
            "type": "rich_text",
            "key": "departure_time",
            "semantic": "出发时间，格式 HH:MM",
        },
        "目的地": {
            "type": "rich_text",
            "key": "destination",
            "semantic": "目的地名称或地址",
        },
        "车型": {"type": "rich_text", "key": "vehicle_type", "semantic": "车辆类型"},
        "人数": {"type": "rich_text", "key": "passenger_count", "semantic": "乘客人数"},
        "行程时长(分钟)": {
            "type": "number",
            "key": "duration_minutes",
            "semantic": "预计行程时长（分钟）",
        },
        "关联行程": {
            "type": "relation",
            "key": "trip_id",
            "semantic": "所属的旅行行程",
            "relation_target": "行程",
            "cardinality": "one",
        },
        "客户": {
            "type": "relation",
            "key": "customer_id",
            "semantic": "乘车的客户列表",
            "relation_target": "客户",
            "cardinality": "many",
        },
        "备注": {"type": "rich_text", "key": "notes", "semantic": "接送备注"},
    },
    # ==================== 客户 ====================
    "客户": {
        "__meta__": {
            "entity_key": "customer",
            "agent": "customer_agent",
            "description": "客户档案信息",
            "business_context": "一条记录 = 一个独立的人（球手）。handicap 字段表示高尔夫水平，数值越低水平越高。",
        },
        "Name": {"type": "title", "key": "name", "semantic": "客户姓名"},
        "生日": {"type": "date", "key": "birthday", "semantic": "出生日期"},
        "国家(必填)": {
            "type": "relation",
            "key": "country",
            "semantic": "国籍",
            "relation_target": "国家",
            "cardinality": "one",
        },
        "差点": {
            "type": "number",
            "key": "handicap",
            "semantic": "高尔夫差点（0-36，越低水平越高）",
        },
        "饮食习惯": {
            "type": "rich_text",
            "key": "dietary_preferences",
            "semantic": "饮食偏好或禁忌",
        },
        "服务需求": {
            "type": "rich_text",
            "key": "service_requirements",
            "semantic": "特殊服务需求",
        },
        "亲友": {
            "type": "relation",
            "key": "relatives",
            "semantic": "关联的家人或朋友",
            "relation_target": "客户",
            "cardinality": "many",
        },
        "参加的行程": {
            "type": "relation",
            "key": "trips",
            "semantic": "客户参与的所有行程",
            "relation_target": "行程",
            "cardinality": "many",
        },
        "会员类型(必填)": {
            "type": "multi_select",
            "key": "membership_type",
            "semantic": "会员等级",
        },
        "备注": {"type": "rich_text", "key": "notes", "semantic": "其他备注"},
        # formula 字段（只读）
        "page_id": {
            "type": "formula",
            "key": "page_id",
            "readonly": True,
            "semantic": "页面 ID（系统生成）",
        },
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
    """从 SCHEMAS 自动生成可写字段列表（排除 readonly 字段和 __meta__）"""
    result = {}
    for db_name, schema in SCHEMAS.items():
        writable = []
        for field_name, field_def in schema.items():
            if field_name == "__meta__":
                continue
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
