"""Notion API 缓存层

使用 cachetools 实现 TTL 缓存，减少 API 调用。
采用"核弹级失效"策略：写操作直接清空整个查询缓存。
"""

import json
from threading import Lock

from cachetools import TTLCache
from cachetools.keys import hashkey

# ==================== 缓存配置 ====================

# 查询缓存：行程、预订等相对稳定的数据 (TTL 5分钟)
QUERY_CACHE: TTLCache = TTLCache(maxsize=256, ttl=300)
QUERY_LOCK = Lock()

# 单页缓存：可能被频繁编辑 (TTL 2分钟)
PAGE_CACHE: TTLCache = TTLCache(maxsize=128, ttl=120)
PAGE_LOCK = Lock()


# ==================== Key 生成函数 ====================


def query_cache_key(
    self,  # NotionClient 实例，忽略
    database_id: str,
    filter: dict | None = None,
    sorts: list | None = None,
    page_size: int = 100,
) -> tuple:
    """生成查询缓存 key（忽略 self 参数）"""
    normalized_db = database_id.replace("-", "")
    filter_str = json.dumps(filter, sort_keys=True) if filter else ""
    sorts_str = json.dumps(sorts, sort_keys=True) if sorts else ""
    return hashkey(normalized_db, filter_str, sorts_str, page_size)


def page_cache_key(self, page_id: str) -> tuple:
    """生成单页缓存 key（忽略 self 参数）"""
    return hashkey(page_id.replace("-", ""))


# ==================== 缓存失效（核弹级策略）====================


def invalidate_all_queries() -> int:
    """清空所有查询缓存（核弹级失效）

    Returns:
        被清除的缓存条目数
    """
    with QUERY_LOCK:
        count = len(QUERY_CACHE)
        QUERY_CACHE.clear()
        return count


def invalidate_page(page_id: str) -> bool:
    """失效指定页面的缓存

    Returns:
        是否成功移除
    """
    key = page_cache_key(None, page_id)
    with PAGE_LOCK:
        return PAGE_CACHE.pop(key, None) is not None


def clear_all_caches() -> None:
    """清除所有缓存（用于测试或强制刷新）"""
    with QUERY_LOCK:
        QUERY_CACHE.clear()
    with PAGE_LOCK:
        PAGE_CACHE.clear()


# ==================== 缓存统计 ====================


def get_cache_stats() -> dict:
    """获取缓存统计信息"""
    return {
        "query_cache": {
            "size": QUERY_CACHE.currsize,
            "maxsize": QUERY_CACHE.maxsize,
            "ttl": QUERY_CACHE.ttl,
        },
        "page_cache": {
            "size": PAGE_CACHE.currsize,
            "maxsize": PAGE_CACHE.maxsize,
            "ttl": PAGE_CACHE.ttl,
        },
    }
