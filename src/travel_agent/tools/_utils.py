"""工具内部辅助函数

包含：
- Notion 属性提取
- 统一的返回格式化
"""

from typing import Any


# =============================================================================
# 统一返回格式
# =============================================================================


def format_tool_result(
    tool_name: str,
    data: list[dict] | dict | str | None = None,
    error: str | None = None,
    empty_message: str = "未找到相关记录",
) -> str:
    """统一格式化工具返回结果

    Args:
        tool_name: 工具名称（如 "高尔夫预订", "天气预报"）
        data: 结果数据（可选）
        error: 错误信息（可选）
        empty_message: 无数据时的提示

    Returns:
        格式化的字符串结果

    示例:
        成功: "【高尔夫预订】找到 3 条记录:\n\n..."
        错误: "【高尔夫预订】错误: 未提供行程 ID"
        无数据: "【高尔夫预订】未找到相关记录"
    """
    prefix = f"【{tool_name}】"

    if error:
        return f"{prefix}错误: {error}"

    if data is None:
        return f"{prefix}{empty_message}"

    if isinstance(data, str):
        return f"{prefix}\n{data}"

    if isinstance(data, list):
        if len(data) == 0:
            return f"{prefix}{empty_message}"
        return f"{prefix}找到 {len(data)} 条记录:\n\n{_format_list(data)}"

    if isinstance(data, dict):
        return f"{prefix}\n{_format_dict(data)}"

    return f"{prefix}{str(data)}"


def _format_list(items: list[dict]) -> str:
    """格式化列表数据"""
    lines = []
    for i, item in enumerate(items, 1):
        lines.append(f"#{i}")
        lines.append(_format_dict(item))
        lines.append("")
    return "\n".join(lines)


def _format_dict(data: dict) -> str:
    """格式化字典数据"""
    lines = []
    for key, value in data.items():
        if value is not None and value != "":
            if isinstance(value, bool):
                value = "是" if value else "否"
            lines.append(f"  {key}: {value}")
    return "\n".join(lines)


# =============================================================================
# Notion 属性提取
# =============================================================================


def _extract_text(value) -> str:
    """从 Notion 属性值中提取纯文本"""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        texts = []
        for item in value:
            if isinstance(item, dict):
                if "plain_text" in item:
                    texts.append(item["plain_text"])
                elif "rich_text" in item:
                    for rt in item.get("rich_text", []):
                        if isinstance(rt, dict):
                            texts.append(rt.get("plain_text", ""))
                elif "text" in item and isinstance(item["text"], dict):
                    texts.append(item["text"].get("content", ""))
        return "".join(texts)
    return str(value) if value else ""
