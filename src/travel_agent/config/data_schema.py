"""业务层数据模型定义

与存储实现（Notion/Airtable/Supabase）无关的业务逻辑：
- 业务实体和字段定义（从 SCHEMAS.__meta__ 自动生成）
- 字段到 Agent 的归属映射
- Agent 能力边界定义
- 语义文档生成（供 Planner 使用）
"""

from ..notion.config import SCHEMAS


# ==================== 从 SCHEMAS 自动构建 ENTITIES ====================

def _build_entities_from_schemas() -> dict:
    """从 SCHEMAS 的 __meta__ 自动构建 ENTITIES

    每个数据库的 __meta__ 包含:
    - entity_key: 业务实体标识
    - agent: 负责的 Agent
    - description: 实体描述
    - business_context: 业务上下文说明
    """
    entities = {}

    for db_name, schema in SCHEMAS.items():
        meta = schema.get("__meta__", {})
        entity_key = meta.get("entity_key")
        if not entity_key:
            continue

        # 提取字段列表（排除 __meta__）
        fields = [
            field_def["key"]
            for field_name, field_def in schema.items()
            if field_name != "__meta__" and isinstance(field_def, dict) and "key" in field_def
        ]

        entities[entity_key] = {
            "name": db_name,
            "description": meta.get("description", ""),
            "business_context": meta.get("business_context", ""),
            "agent": meta.get("agent", f"{entity_key}_agent"),
            "fields": fields,
        }

    return entities


# 从 SCHEMAS 自动生成的实体定义
_AUTO_ENTITIES = _build_entities_from_schemas()

# 合并手动定义的实体（不在 Notion 中的）
ENTITIES = {
    **_AUTO_ENTITIES,
    # 天气和搜索不在 Notion 中，手动定义
    "weather": {
        "name": "天气",
        "description": "天气预报查询",
        "business_context": "通过外部 API 获取天气预报，需要提供地点和日期。",
        "agent": "weather_agent",
        "fields": ["weather_forecast", "temperature", "conditions"],
    },
    "search": {
        "name": "搜索",
        "description": "互联网公开信息搜索",
        "business_context": "搜索酒店评价、球场攻略、汇率、新闻等公开信息。",
        "agent": "search_agent",
        "fields": ["reviews", "ratings", "tips", "exchange_rate", "news"],
    },
}


# ==================== 语义文档生成 ====================

def generate_semantic_docs() -> str:
    """生成完整的数据模型语义文档（供 Planner Prompt 使用）

    输出格式：
    ### entity_key (数据库名)
    **含义**: description
    **重要**: business_context

    | 字段 | 类型 | 语义 | 关联 |
    |------|------|------|------|
    | key | type | semantic | → target (cardinality) |
    """
    docs = []

    for db_name, schema in SCHEMAS.items():
        meta = schema.get("__meta__", {})
        if not meta:
            continue

        entity_key = meta.get("entity_key", db_name)
        description = meta.get("description", "")
        context = meta.get("business_context", "")

        docs.append(f"### {entity_key} ({db_name})")
        docs.append(f"**含义**: {description}")
        if context:
            docs.append(f"**重要**: {context}")
        docs.append("")
        docs.append("| 字段 | 类型 | 语义 | 关联 |")
        docs.append("|------|------|------|------|")

        for field_name, field_def in schema.items():
            if field_name == "__meta__" or not isinstance(field_def, dict):
                continue
            key = field_def.get("key", field_name)
            ftype = field_def.get("type", "?")
            semantic = field_def.get("semantic", "")
            relation_target = field_def.get("relation_target", "")
            cardinality = field_def.get("cardinality", "")

            # 格式化关联信息
            relation_str = ""
            if relation_target:
                relation_str = f"→ {relation_target}"
                if cardinality:
                    relation_str += f" ({cardinality})"

            docs.append(f"| {key} | {ftype} | {semantic} | {relation_str} |")

        docs.append("")

    # 添加手动定义实体的文档
    for entity_key in ["weather", "search"]:
        entity = ENTITIES.get(entity_key)
        if not entity:
            continue
        docs.append(f"### {entity_key} (外部数据源)")
        docs.append(f"**含义**: {entity['description']}")
        if entity.get("business_context"):
            docs.append(f"**重要**: {entity['business_context']}")
        docs.append("")
        docs.append("| 字段 | 类型 | 语义 | 关联 |")
        docs.append("|------|------|------|------|")
        for field in entity["fields"]:
            docs.append(f"| {field} | - | - | |")
        docs.append("")

    return "\n".join(docs)


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

def _build_agent_capabilities() -> dict:
    """从 ENTITIES 自动构建 Agent 能力定义"""
    # Agent 到实体的映射（一个 Agent 可能处理多个实体）
    agent_entities = {}
    for entity_key, entity in ENTITIES.items():
        agent = entity["agent"]
        agent_entities.setdefault(agent, []).append(entity_key)

    capabilities = {}
    for agent, entity_keys in agent_entities.items():
        # 合并所有实体的字段
        all_fields = []
        for ek in entity_keys:
            all_fields.extend(ENTITIES[ek]["fields"])
        # 去重
        all_fields = list(dict.fromkeys(all_fields))

        capabilities[agent] = {
            "description": ENTITIES[entity_keys[0]].get("description", ""),
            "supported_fields": all_fields,
            "external_fields": [],
        }

    # 手动补充外部字段（需要其他 Agent 配合的字段）
    if "hotel_agent" in capabilities:
        capabilities["hotel_agent"]["external_fields"] = ["reviews", "ratings", "tips", "nearby", "weather"]
    if "golf_agent" in capabilities:
        capabilities["golf_agent"]["external_fields"] = ["course_reviews", "course_tips", "weather"]

    return capabilities


AGENT_CAPABILITIES = _build_agent_capabilities()


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
