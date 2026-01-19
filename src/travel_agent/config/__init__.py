"""配置模块

业务层配置（与存储实现无关）
"""
from .data_schema import (
    ENTITIES,
    FIELD_OWNERSHIP,
    AGENT_CAPABILITIES,
    ROUTING_RULES,
    format_field_ownership_for_prompt,
)

__all__ = [
    "ENTITIES",
    "FIELD_OWNERSHIP",
    "AGENT_CAPABILITIES",
    "ROUTING_RULES",
    "format_field_ownership_for_prompt",
]
