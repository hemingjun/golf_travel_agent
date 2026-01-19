"""业务层数据模型定义

与存储实现（Notion/Airtable/Supabase）无关的业务逻辑：
- 业务实体和字段定义（从 SCHEMAS 自动生成）
- 字段到 Agent 的归属映射
- Agent 能力边界定义
"""

from ..notion.config import SCHEMAS

# ==================== 实体到数据库的映射 ====================

ENTITY_SOURCES = {
    "hotel": ["酒店", "酒店组件"],  # 酒店实体从这两个数据库获取字段
    "golf": ["高尔夫组件"],
    "logistics": ["物流组件"],
    "customer": ["客户"],
    "itinerary": ["行程组件"],
}


def _extract_fields(db_names: list[str]) -> list[str]:
    """从 SCHEMAS 提取指定数据库的所有英文 key"""
    fields = []
    seen = set()
    for db_name in db_names:
        schema = SCHEMAS.get(db_name, {})
        for field_def in schema.values():
            if isinstance(field_def, dict) and "key" in field_def:
                key = field_def["key"]
                if key not in seen:
                    fields.append(key)
                    seen.add(key)
    return fields


# ==================== 业务实体定义（字段从 SCHEMAS 自动生成）====================

ENTITIES = {
    "hotel": {
        "name": "酒店",
        "description": "酒店预订和酒店主数据",
        "agent": "hotel_agent",
        "fields": _extract_fields(ENTITY_SOURCES["hotel"]),
    },
    "golf": {
        "name": "高尔夫",
        "description": "球场预订和打球安排",
        "agent": "golf_agent",
        "fields": _extract_fields(ENTITY_SOURCES["golf"]),
    },
    "logistics": {
        "name": "物流",
        "description": "车辆接送安排",
        "agent": "logistics_agent",
        "fields": _extract_fields(ENTITY_SOURCES["logistics"]),
    },
    "customer": {
        "name": "客户",
        "description": "客户档案信息",
        "agent": "customer_agent",
        "fields": _extract_fields(ENTITY_SOURCES["customer"]),
    },
    "itinerary": {
        "name": "行程",
        "description": "日程事件安排（不含实体详情）",
        "agent": "itinerary_agent",
        "fields": _extract_fields(ENTITY_SOURCES["itinerary"]),
    },
    "weather": {
        "name": "天气",
        "description": "天气预报查询",
        "agent": "weather_agent",
        # 天气字段不在 Notion 中，手动定义
        "fields": ["weather_forecast", "temperature", "conditions"],
    },
    "search": {
        "name": "搜索",
        "description": "互联网公开信息搜索",
        "agent": "search_agent",
        # 搜索字段不在 Notion 中，手动定义
        "fields": ["reviews", "ratings", "tips", "exchange_rate", "news"],
    },
}


# ==================== 字段归属映射 ====================

def _build_field_ownership() -> dict[str, str]:
    """从 ENTITIES 构建字段到 Agent 的归属映射"""
    ownership = {}
    for entity in ENTITIES.values():
        agent = entity["agent"]
        for field in entity["fields"]:
            ownership[field] = agent
    return ownership


FIELD_OWNERSHIP = _build_field_ownership()


# ==================== Agent 能力定义 ====================

AGENT_CAPABILITIES = {
    "hotel_agent": {
        "description": "酒店详情（名称、地址、电话、星级、房型、入住退房）",
        "supported_fields": ENTITIES["hotel"]["fields"],
        "external_fields": ["reviews", "ratings", "tips", "nearby", "weather"],
    },
    "golf_agent": {
        "description": "球场预订详情（Teetime、球手、Caddie、球场名称）",
        "supported_fields": ENTITIES["golf"]["fields"],
        "external_fields": ["course_reviews", "course_tips", "weather"],
    },
    "logistics_agent": {
        "description": "车辆安排（出发时间、目的地、车型）",
        "supported_fields": ENTITIES["logistics"]["fields"],
        "external_fields": [],
    },
    "customer_agent": {
        "description": "客户信息（姓名、差点、饮食习惯）",
        "supported_fields": ENTITIES["customer"]["fields"],
        "external_fields": [],
    },
    "itinerary_agent": {
        "description": "行程事件（日期、事件类型、事件内容）。不含酒店/球场详情",
        "supported_fields": ENTITIES["itinerary"]["fields"],
        "external_fields": [],
    },
    "weather_agent": {
        "description": "天气预报",
        "supported_fields": ENTITIES["weather"]["fields"],
        "external_fields": [],
    },
    "search_agent": {
        "description": "互联网搜索（汇率、评价、攻略、新闻）",
        "supported_fields": ENTITIES["search"]["fields"],
        "external_fields": [],
    },
}


# ==================== 路由规则文本 ====================

ROUTING_RULES = """
**必须遵循的路由规则**：
- 酒店名称/地址/电话/星级/早餐信息 → `hotel_agent` (不是 itinerary_agent)
- 球场名称/Teetime/Caddie/Buggie → `golf_agent`
- 日程事件/行程时长/事件类型/事件内容 → `itinerary_agent`
- 客户姓名/差点/饮食习惯/服务需求 → `customer_agent`
- 车辆/出发时间/目的地/车型 → `logistics_agent`
- 天气预报 → `weather_agent`
- 评价/汇率/攻略/新闻 → `search_agent`

**❌ 常见错误**：
- `[itinerary_agent] 获取酒店名称` → 行程组件只有酒店 relation ID，没有酒店详情
- `[itinerary_agent] 获取 Teetime` → 行程组件的 Teetime 是简略文本

**✅ 正确做法**：
- `[hotel_agent] 获取酒店名称、地址、电话`
- `[golf_agent] 获取 Teetime、球手列表`
"""


def format_field_ownership_for_prompt() -> str:
    """格式化字段归属表供 Planner prompt 使用"""
    agent_fields: dict[str, list[str]] = {}
    for field, agent in FIELD_OWNERSHIP.items():
        agent_fields.setdefault(agent, []).append(field)

    lines = []
    for agent in sorted(agent_fields.keys()):
        fields = agent_fields[agent]
        lines.append(f"- **{agent}**: {', '.join(fields)}")
    return "\n".join(lines)
