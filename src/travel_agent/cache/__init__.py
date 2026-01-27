"""缓存管理模块

统一管理所有缓存的生命周期和失效策略。
"""

from .manager import CacheManager, cache_manager

__all__ = ["CacheManager", "cache_manager"]
