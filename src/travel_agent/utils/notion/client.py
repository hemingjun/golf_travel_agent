"""Notion API 客户端（带 TTL 缓存）"""

import os
from typing import Any

from cachetools import cached
from notion_client import Client as NotionSDK

from .cache import (
    PAGE_CACHE,
    PAGE_LOCK,
    QUERY_CACHE,
    QUERY_LOCK,
    invalidate_all_queries,
    invalidate_page,
    page_cache_key,
    query_cache_key,
)
from .config import DATABASES, SCHEMAS, normalize_id
from .types import build_page_properties, parse_page_properties


def _get_id_to_name() -> dict[str, str]:
    """获取 ID -> 名称 的反向映射（使用标准化 ID）"""
    return {normalize_id(v): k for k, v in DATABASES.items()}


# ==================== 单例模式 ====================

_client_instance: "NotionClient | None" = None


def get_client() -> "NotionClient":
    """获取 NotionClient 单例

    使用单例模式可以保留缓存（schema、data_source_id），避免重复 API 调用。
    """
    global _client_instance
    if _client_instance is None:
        _client_instance = NotionClient()
    return _client_instance


def clear_client_cache() -> None:
    """清除单例客户端（用于测试或重新初始化）"""
    global _client_instance
    _client_instance = None


class NotionClient:
    """Notion API 统一客户端

    基于 2025-09-03 版本 API，使用 data_source_id 替代 database_id
    """

    def __init__(self, token: str | None = None):
        """初始化客户端

        Args:
            token: Notion Integration Token，如果不提供则从环境变量 NOTION_TOKEN 获取
        """
        self.token = token or os.getenv("NOTION_TOKEN")
        if not self.token:
            raise ValueError("需要提供 NOTION_TOKEN")
        self._client = NotionSDK(auth=self.token)
        self._schema_cache: dict[str, dict] = {}
        self._data_source_cache: dict[str, str] = {}  # database_id -> data_source_id

    def _get_data_source_id(self, database_id: str) -> str:
        """获取数据库对应的 data_source_id

        Notion 2025-09-03 API 中 database_id 和 data_source_id 是不同的。
        需要先调用 databases.retrieve() 获取真正的 data_source_id。
        """
        normalized = normalize_id(database_id)
        if normalized in self._data_source_cache:
            return self._data_source_cache[normalized]

        # 调用 API 获取 data_source_id
        try:
            db_info = self._client.databases.retrieve(database_id=database_id)
            data_sources = db_info.get("data_sources", [])
            if data_sources:
                ds_id = data_sources[0]["id"]
                self._data_source_cache[normalized] = ds_id
                return ds_id
        except Exception:
            pass

        # 兼容旧版 API 或获取失败时使用原 ID
        return database_id

    # ==================== 数据库操作 ====================

    def search_database(self, name: str) -> dict | None:
        """按名称搜索数据库

        Args:
            name: 数据库名称

        Returns:
            数据库信息字典，包含 id, name, data_source_id, properties
        """
        results = self._client.search(
            query=name, filter={"property": "object", "value": "data_source"}
        )

        for item in results.get("results", []):
            # 获取标题
            title_array = item.get("title", [])
            if title_array:
                db_name = title_array[0].get("plain_text", "")
                if db_name == name:
                    # 从搜索结果中提取 properties（如果有）
                    properties = item.get("properties", {})
                    schema = (
                        {k: v.get("type") for k, v in properties.items()}
                        if properties
                        else None
                    )

                    return {
                        "id": item["id"],
                        "name": db_name,
                        "data_source_id": item["id"],
                        "properties": properties,
                        "schema": schema,
                    }
        return None

    def get_schema(self, data_source_id: str, use_cache: bool = True) -> dict:
        """获取数据源的 schema

        Args:
            data_source_id: 数据源 ID
            use_cache: 是否使用缓存

        Returns:
            属性名到属性类型的映射字典
        """
        # 标准化 ID 用于缓存和查找
        normalized_id = normalize_id(data_source_id)

        if use_cache and normalized_id in self._schema_cache:
            return self._schema_cache[normalized_id]

        # 优先使用预定义的 schema
        db_name = _get_id_to_name().get(normalized_id)
        if db_name and db_name in SCHEMAS:
            schema = SCHEMAS[db_name]
            self._schema_cache[normalized_id] = schema
            return schema

        # 尝试从 API 获取
        try:
            db_info = self._client.databases.retrieve(database_id=data_source_id)
            properties = db_info.get("properties", {})
            schema = {name: prop.get("type") for name, prop in properties.items()}
            self._schema_cache[normalized_id] = schema
            return schema
        except Exception:
            return {}

    def get_schema_detailed(self, data_source_id: str) -> dict:
        """获取数据源的详细 schema（包含选项等信息）

        Args:
            data_source_id: 数据源 ID

        Returns:
            完整的属性信息字典
        """
        db_info = self._client.databases.retrieve(database_id=data_source_id)
        return db_info.get("properties", {})

    def list_databases(self) -> list[dict]:
        """列出所有可访问的数据库

        Returns:
            数据库信息列表
        """
        results = self._client.search(
            filter={"property": "object", "value": "data_source"}
        )

        databases = []
        for item in results.get("results", []):
            title_array = item.get("title", [])
            name = title_array[0].get("plain_text", "") if title_array else ""
            databases.append(
                {
                    "id": item["id"],
                    "name": name,
                    "data_source_id": item["id"],
                }
            )
        return databases

    # ==================== 页面操作（带 TTL 缓存）====================

    @cached(cache=QUERY_CACHE, key=query_cache_key, lock=QUERY_LOCK)
    def query_pages(
        self,
        database_id: str,
        filter: dict | None = None,
        sorts: list | None = None,
        page_size: int = 100,
    ) -> list[dict]:
        """查询数据库中的页面（带 TTL 缓存，5分钟）

        Args:
            database_id: 数据库 ID（会自动转换为 data_source_id）
            filter: 过滤条件
            sorts: 排序条件
            page_size: 每页数量

        Returns:
            页面列表，每个页面的属性已解析
        """
        # 获取真正的 data_source_id
        data_source_id = self._get_data_source_id(database_id)
        schema = self.get_schema(database_id)

        query_params: dict[str, Any] = {"page_size": page_size}
        if filter:
            query_params["filter"] = filter
        if sorts:
            query_params["sorts"] = sorts

        # 使用 data_sources 端点查询
        results = self._client.data_sources.query(
            data_source_id=data_source_id, **query_params
        )

        pages = []
        for page in results.get("results", []):
            parsed = {
                "id": page["id"],
                "created_time": page.get("created_time"),
                "last_edited_time": page.get("last_edited_time"),
                "properties": parse_page_properties(page.get("properties", {}), schema),
            }
            pages.append(parsed)

        return pages

    def query_all_pages(
        self,
        database_id: str,
        filter: dict | None = None,
        sorts: list | None = None,
    ) -> list[dict]:
        """查询数据库中的所有页面（自动分页）

        Args:
            database_id: 数据库 ID（会自动转换为 data_source_id）
            filter: 过滤条件
            sorts: 排序条件

        Returns:
            所有页面列表
        """
        # 获取真正的 data_source_id
        data_source_id = self._get_data_source_id(database_id)
        schema = self.get_schema(database_id)
        all_pages = []
        start_cursor = None

        while True:
            query_params: dict[str, Any] = {"page_size": 100}
            if filter:
                query_params["filter"] = filter
            if sorts:
                query_params["sorts"] = sorts
            if start_cursor:
                query_params["start_cursor"] = start_cursor

            results = self._client.data_sources.query(
                data_source_id=data_source_id, **query_params
            )

            for page in results.get("results", []):
                parsed = {
                    "id": page["id"],
                    "created_time": page.get("created_time"),
                    "last_edited_time": page.get("last_edited_time"),
                    "properties": parse_page_properties(
                        page.get("properties", {}), schema
                    ),
                }
                all_pages.append(parsed)

            if not results.get("has_more"):
                break
            start_cursor = results.get("next_cursor")

        return all_pages

    def create_page(self, data_source_id: str, data: dict) -> dict:
        """在数据源中创建新页面

        Args:
            data_source_id: 数据源 ID
            data: 页面数据，键为属性名，值为 Python 值

        Returns:
            创建的页面信息
        """
        schema = self.get_schema(data_source_id)
        properties = build_page_properties(data, schema)

        page = self._client.pages.create(
            parent={"type": "database_id", "database_id": data_source_id},
            properties=properties,
        )

        # 核弹级失效：清空所有查询缓存
        invalidate_all_queries()

        return {
            "id": page["id"],
            "created_time": page.get("created_time"),
            "properties": parse_page_properties(page.get("properties", {}), schema),
        }

    def update_page(
        self, page_id: str, data: dict, data_source_id: str | None = None
    ) -> dict:
        """更新页面

        Args:
            page_id: 页面 ID
            data: 要更新的数据
            data_source_id: 数据源 ID（用于获取 schema）

        Returns:
            更新后的页面信息
        """
        # 如果没有提供 data_source_id，先获取页面信息
        if not data_source_id:
            page_info = self._client.pages.retrieve(page_id=page_id)
            parent = page_info.get("parent", {})
            data_source_id = parent.get("database_id")

        schema = self.get_schema(data_source_id) if data_source_id else {}
        properties = build_page_properties(data, schema) if schema else data

        page = self._client.pages.update(page_id=page_id, properties=properties)

        # 缓存失效：清除该页面缓存 + 核弹级清空查询缓存
        invalidate_page(page_id)
        invalidate_all_queries()

        return {
            "id": page["id"],
            "last_edited_time": page.get("last_edited_time"),
            "properties": parse_page_properties(page.get("properties", {}), schema),
        }

    def archive_page(self, page_id: str) -> bool:
        """归档（软删除）页面

        Args:
            page_id: 页面 ID

        Returns:
            是否成功
        """
        try:
            self._client.pages.update(page_id=page_id, archived=True)
            # 缓存失效：清除该页面缓存 + 核弹级清空查询缓存
            invalidate_page(page_id)
            invalidate_all_queries()
            return True
        except Exception:
            return False

    @cached(cache=PAGE_CACHE, key=page_cache_key, lock=PAGE_LOCK)
    def get_page(self, page_id: str) -> dict:
        """获取单个页面（带 TTL 缓存，2分钟）

        Args:
            page_id: 页面 ID

        Returns:
            页面信息
        """
        page = self._client.pages.retrieve(page_id=page_id)
        parent = page.get("parent", {})
        data_source_id = parent.get("database_id")

        schema = self.get_schema(data_source_id) if data_source_id else {}

        return {
            "id": page["id"],
            "created_time": page.get("created_time"),
            "last_edited_time": page.get("last_edited_time"),
            "properties": parse_page_properties(page.get("properties", {}), schema),
        }
