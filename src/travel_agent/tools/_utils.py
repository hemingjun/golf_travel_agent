"""工具内部辅助函数"""


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
