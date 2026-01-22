"""Notion 属性类型转换"""

from datetime import date, datetime
from typing import Any


def parse_rich_text(rich_text_array: list) -> str:
    """解析 rich_text 数组为纯文本"""
    if not rich_text_array:
        return ""
    return "".join(item.get("plain_text", "") for item in rich_text_array)


def parse_property(prop_type: str, prop_data: dict) -> Any:
    """将 Notion 属性值转换为 Python 值

    Args:
        prop_type: 属性类型
        prop_data: 属性数据

    Returns:
        转换后的 Python 值
    """
    value = prop_data.get(prop_type)

    if value is None:
        return None

    match prop_type:
        case "title":
            return parse_rich_text(value)

        case "rich_text":
            return parse_rich_text(value)

        case "number":
            return value

        case "select":
            return value.get("name") if value else None

        case "multi_select":
            return [item.get("name") for item in value] if value else []

        case "status":
            return value.get("name") if value else None

        case "date":
            if not value:
                return None
            start = value.get("start")
            if start:
                # 尝试解析为 datetime 或 date
                try:
                    if "T" in start:
                        return datetime.fromisoformat(start.replace("Z", "+00:00"))
                    return date.fromisoformat(start)
                except ValueError:
                    return start
            return None

        case "checkbox":
            return value

        case "url":
            return value

        case "email":
            return value

        case "phone_number":
            return value

        case "relation":
            return [item.get("id") for item in value] if value else []

        case "people":
            return [item.get("id") for item in value] if value else []

        case "files":
            result = []
            for file in value or []:
                if file.get("type") == "external":
                    result.append(file.get("external", {}).get("url"))
                elif file.get("type") == "file":
                    result.append(file.get("file", {}).get("url"))
            return result

        case "formula":
            formula_type = value.get("type")
            return value.get(formula_type)

        case "rollup":
            rollup_type = value.get("type")
            return value.get(rollup_type)

        case "created_time" | "last_edited_time":
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                return value

        case "created_by" | "last_edited_by":
            return value.get("id") if value else None

        case "unique_id":
            prefix = value.get("prefix", "")
            number = value.get("number", 0)
            return f"{prefix}{number}" if prefix else number

        case _:
            return value


def build_property(prop_type: str, value: Any) -> dict:
    """将 Python 值转换为 Notion 属性格式

    Args:
        prop_type: 属性类型
        value: Python 值

    Returns:
        Notion 属性格式的字典
    """
    if value is None:
        return {prop_type: None}

    match prop_type:
        case "title":
            return {"title": [{"type": "text", "text": {"content": str(value)}}]}

        case "rich_text":
            return {"rich_text": [{"type": "text", "text": {"content": str(value)}}]}

        case "number":
            return {"number": float(value) if value else None}

        case "select":
            return {"select": {"name": str(value)} if value else None}

        case "multi_select":
            if isinstance(value, str):
                value = [value]
            return {"multi_select": [{"name": str(v)} for v in value]}

        case "status":
            return {"status": {"name": str(value)} if value else None}

        case "date":
            if isinstance(value, datetime):
                return {"date": {"start": value.isoformat()}}
            elif isinstance(value, date):
                return {"date": {"start": value.isoformat()}}
            elif isinstance(value, str):
                return {"date": {"start": value}}
            return {"date": None}

        case "checkbox":
            return {"checkbox": bool(value)}

        case "url":
            return {"url": str(value) if value else None}

        case "email":
            return {"email": str(value) if value else None}

        case "phone_number":
            return {"phone_number": str(value) if value else None}

        case "relation":
            if isinstance(value, str):
                value = [value]
            return {"relation": [{"id": v} for v in value]}

        case "people":
            if isinstance(value, str):
                value = [value]
            return {"people": [{"id": v} for v in value]}

        case "files":
            if isinstance(value, str):
                value = [value]
            return {
                "files": [
                    {
                        "type": "external",
                        "name": url.split("/")[-1],
                        "external": {"url": url},
                    }
                    for url in value
                ]
            }

        case _:
            return {prop_type: value}


def _get_field_type(schema: dict, field_name: str) -> str | None:
    """从 schema 获取字段类型（兼容新旧格式）"""
    field_def = schema.get(field_name)
    if isinstance(field_def, dict):
        return field_def.get("type")
    return field_def


def parse_page_properties(properties: dict, schema: dict | None = None) -> dict:
    """解析页面的所有属性

    Args:
        properties: Notion 页面的 properties 字典
        schema: 可选的数据库 schema，用于获取属性类型

    Returns:
        解析后的属性字典（中文 key）
    """
    result = {}
    for name, prop_data in properties.items():
        prop_type = prop_data.get("type")
        if prop_type:
            result[name] = parse_property(prop_type, prop_data)
    return result


def transform_props(props: dict, schema: dict) -> dict:
    """将 Notion 属性转换为业务字典（中文 key → 英文 key）

    这是核心的字段映射函数，根据 schema 中的 key 定义进行转换。

    Args:
        props: 已解析的属性字典（中文 key）
        schema: 数据库 schema，包含 {"中文名": {"type": "...", "key": "english_key"}}

    Returns:
        转换后的业务字典（英文 key），值为空时返回空字符串或默认值
    """
    result = {}
    for notion_name, value in props.items():
        if notion_name in schema:
            field_def = schema[notion_name]
            if isinstance(field_def, dict) and "key" in field_def:
                key = field_def["key"]
                # 确保值不为 None
                result[key] = value if value is not None else ""
            else:
                # 兼容旧格式：没有 key 定义时使用原字段名
                result[notion_name] = value if value is not None else ""
    return result


def build_page_properties(data: dict, schema: dict) -> dict:
    """构建页面的 properties

    Args:
        data: Python 数据字典
        schema: 数据库 schema，包含属性名到类型的映射

    Returns:
        Notion 格式的 properties 字典
    """
    properties = {}
    for name, value in data.items():
        if name in schema:
            prop_type = _get_field_type(schema, name)
            if prop_type:
                properties[name] = build_property(prop_type, value)
    return properties
