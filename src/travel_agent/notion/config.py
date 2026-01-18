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
SCHEMAS = {
    # 行程组件 - 实际名称: 行程数据库_行程事件
    "行程组件": {
        "标题": "title",
        "日期": "date",
        "事件类型": "select",
        "事件内容": "rich_text",
        "行程": "relation",
        "球场": "relation",
        "酒店": "relation",
        "Teetime": "rich_text",
        "行程时长": "rich_text",
        "天气": "rich_text",
        "是否提醒": "checkbox",
        "提醒状态": "select",
    },
    # 高尔夫组件 - 实际名称: 行程数据库_高尔夫组件
    "高尔夫组件": {
        "名称": "title",
        "PlayDate": "date",
        "Teetime": "rich_text",
        "关联行程": "relation",
        "关联球场": "relation",
        "球手": "relation",
        "Notes": "rich_text",
        "Caddie": "checkbox",
        "Buggie": "checkbox",
        # rollup 字段（只读）
        "中文名": "rollup",
        "地址": "rollup",
        "电话": "rollup",
    },
    # 酒店组件 - 实际名称: 行程数据库_酒店组件
    "酒店组件": {
        "名称": "title",
        "入住日期": "date",
        "退房日期": "date",
        "关联行程": "relation",
        "酒店": "relation",
        "客户": "relation",
        "房型": "select",
        "房间等级": "select",
        "景观": "select",
        "备注": "rich_text",
        "confirmation #": "rich_text",
    },
    # 物流组件 - 实际名称: 行程数据库_物流组件
    "物流组件": {
        "名称": "title",
        "日期": "date",
        "出发时间": "rich_text",
        "目的地": "rich_text",
        "车型": "rich_text",
        "人数": "rich_text",
        "行程时长(分钟)": "number",
        "关联行程": "relation",
        "客户": "relation",
        "备注": "rich_text",
    },
    # 客户 - 实际名称: 人员数据库_客户
    "客户": {
        "Name": "title",
        "国家(必填)": "relation",
        "差点": "number",
        "饮食习惯": "rich_text",
        "服务需求": "rich_text",
        "亲友": "relation",
        "参加的行程": "relation",
        "会员类型(必填)": "multi_select",
        "备注": "rich_text",
        # formula 字段（只读）
        "page_id": "formula",
    },
}

# 可写字段（排除 rollup/formula 等只读字段）
WRITABLE_FIELDS = {
    "行程组件": [
        "标题", "日期", "事件类型", "事件内容",
        "行程", "球场", "酒店", "Teetime",
        "行程时长", "天气", "是否提醒", "提醒状态",
    ],
    "高尔夫组件": [
        "名称", "PlayDate", "Teetime",
        "关联行程", "关联球场", "球手",
        "Notes", "Caddie", "Buggie",
    ],
    "酒店组件": [
        "名称", "入住日期", "退房日期",
        "关联行程", "酒店", "客户",
        "房型", "房间等级", "景观",
        "备注", "confirmation #",
    ],
    "物流组件": [
        "名称", "日期", "出发时间", "目的地",
        "车型", "人数", "行程时长(分钟)",
        "关联行程", "客户", "备注",
    ],
}
