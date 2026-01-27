"""统一缓存管理器

整合 SESSION_CONTEXT, WELCOME_CACHE, TRIP_SESSIONS 的管理，
提供统一的失效策略和清理机制。
"""

from datetime import datetime, timedelta
from typing import Any


class CacheManager:
    """统一缓存管理器

    管理三类缓存：
    - session_context: 会话上下文 (thread_id -> context)
    - welcome_cache: 欢迎消息 (cache_key -> greeting data)
    - trip_sessions: 行程会话映射 (trip_id -> set[thread_id])
    """

    # 缓存过期配置
    WELCOME_TTL = timedelta(hours=3)
    SESSION_CLEANUP_DAYS = 3  # 行程结束后 N 天清理

    def __init__(self):
        self._session_context: dict[str, dict] = {}
        self._welcome_cache: dict[str, dict] = {}
        self._trip_sessions: dict[str, set[str]] = {}

    # =========================================================================
    # Session Context 管理
    # =========================================================================

    def get_session(self, thread_id: str) -> dict | None:
        """获取会话上下文"""
        return self._session_context.get(thread_id)

    def set_session(
        self,
        thread_id: str,
        trip_id: str,
        customer_id: str,
        date: str,
        expires_after: str | None = None,
    ) -> None:
        """设置会话上下文"""
        self._session_context[thread_id] = {
            "date": date,
            "trip_id": trip_id,
            "customer_id": customer_id,
            "expires_after": expires_after,
        }
        # 关联到行程
        if trip_id not in self._trip_sessions:
            self._trip_sessions[trip_id] = set()
        self._trip_sessions[trip_id].add(thread_id)

    def clear_session(self, thread_id: str) -> None:
        """清除单个会话"""
        self._session_context.pop(thread_id, None)

    # =========================================================================
    # Welcome Cache 管理
    # =========================================================================

    def get_welcome_cache_key(self, trip_id: str, customer_id: str, date: str) -> str:
        """生成 welcome 缓存 key"""
        return f"{trip_id}:{customer_id}:{date}"

    def get_welcome(self, cache_key: str) -> dict | None:
        """获取缓存的欢迎消息，过期返回 None"""
        if cache_key not in self._welcome_cache:
            return None
        cached = self._welcome_cache[cache_key]
        if datetime.now() > cached["expires_at"]:
            del self._welcome_cache[cache_key]
            return None
        return cached

    def set_welcome(
        self,
        cache_key: str,
        greeting: str,
        customer_name: str,
        thread_id: str,
    ) -> None:
        """设置欢迎消息缓存"""
        self._welcome_cache[cache_key] = {
            "greeting": greeting,
            "customer_name": customer_name,
            "thread_id": thread_id,
            "expires_at": datetime.now() + self.WELCOME_TTL,
        }

    def clear_welcome_cache(self) -> int:
        """清空所有欢迎消息缓存，返回清理数量"""
        count = len(self._welcome_cache)
        self._welcome_cache.clear()
        return count

    # =========================================================================
    # 行程级别的缓存管理
    # =========================================================================

    def cleanup_trip(self, trip_id: str) -> int:
        """清理指定行程的所有会话缓存

        Returns: 清理的会话数量
        """
        if trip_id not in self._trip_sessions:
            return 0
        thread_ids = self._trip_sessions.pop(trip_id)
        count = 0
        for thread_id in thread_ids:
            self._session_context.pop(thread_id, None)
            count += 1
        return count

    def cleanup_expired_sessions(self) -> int:
        """清理所有过期会话（行程结束 N 天后）

        Returns: 清理的会话总数
        """
        today = datetime.now().date()
        expired_trips: list[str] = []

        for trip_id in list(self._trip_sessions.keys()):
            thread_ids = self._trip_sessions.get(trip_id, set())
            if not thread_ids:
                continue
            # 从该行程的任一会话获取 expires_after
            sample_thread_id = next(iter(thread_ids))
            ctx = self._session_context.get(sample_thread_id, {})
            expires_after = ctx.get("expires_after")
            if expires_after:
                try:
                    trip_end = datetime.strptime(expires_after, "%Y-%m-%d").date()
                    cleanup_date = trip_end + timedelta(days=self.SESSION_CLEANUP_DAYS)
                    if today > cleanup_date:
                        expired_trips.append(trip_id)
                except ValueError:
                    pass

        total_cleaned = 0
        for trip_id in expired_trips:
            total_cleaned += self.cleanup_trip(trip_id)
            print(f"[Cache] Trip {trip_id[:8]}... expired, cleaned sessions")

        return total_cleaned

    # =========================================================================
    # 统一失效策略
    # =========================================================================

    def invalidate_on_login(self) -> None:
        """登录时失效相关缓存

        用户登录时清空 welcome 缓存，确保下次获取最新数据。
        """
        count = self.clear_welcome_cache()
        if count > 0:
            print(f"[Cache] Login triggered, cleared {count} welcome cache entries")

    def invalidate_on_data_change(self, trip_id: str | None = None) -> None:
        """数据变更时失效相关缓存

        当 Notion 数据变更时调用，清除相关的 welcome 缓存。
        """
        if trip_id:
            # 只清除该行程相关的 welcome 缓存
            keys_to_remove = [
                k for k in self._welcome_cache.keys()
                if k.startswith(f"{trip_id}:")
            ]
            for key in keys_to_remove:
                del self._welcome_cache[key]
            if keys_to_remove:
                print(f"[Cache] Data change, cleared {len(keys_to_remove)} welcome entries for trip {trip_id[:8]}...")
        else:
            # 清空所有 welcome 缓存
            self.clear_welcome_cache()

    # =========================================================================
    # 统计和调试
    # =========================================================================

    def stats(self) -> dict[str, Any]:
        """获取缓存统计信息"""
        return {
            "session_count": len(self._session_context),
            "welcome_count": len(self._welcome_cache),
            "trip_count": len(self._trip_sessions),
        }


# 全局单例
cache_manager = CacheManager()
