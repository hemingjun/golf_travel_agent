# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

基于 LangGraph ReAct Agent 构建的高尔夫旅行智能助手，通过 Notion 管理行程数据。支持 CLI、FastAPI Server、Chainlit Web UI 三种运行模式，以及管理员和客户两种用户角色。

## 常用命令

```bash
# CLI 模式（单行程会话）
uv run python main.py -t <行程ID> -u admin       # 管理员模式
uv run python main.py -t <行程ID> -u <客户PageID> # 客户模式
uv run python main.py -t <行程ID> -u admin -d    # 调试模式（显示思维链）

# FastAPI Server（多租户服务端）
uv run python -m travel_agent.server             # 启动 API 服务 (端口 8080)
uv run uvicorn travel_agent.server:app --reload  # 开发模式

# Docker 部署
docker build -t golf-travel-agent .
docker run -p 8080:8080 --env-file .env golf-travel-agent

# 开发工具
uv run pytest                    # 运行测试
uv run ruff check .              # 代码检查
uv run ruff format .             # 代码格式化
```

## 环境变量

必需: `GOOGLE_API_KEY`, `NOTION_TOKEN`, `NOTION_DB_GOLF`, `NOTION_DB_HOTEL`, `NOTION_DB_LOGISTIC`, `NOTION_DB_ITINERARY`, `NOTION_DB_CUSTOMER`

可选: `OPENWEATHER_API_KEY`, `DB_PATH`（SQLite 检查点路径，默认 `/app/data/checkpoints.db`）

## 架构

### ReAct Agent 模式

```text
用户输入 → ReAct Agent (Gemini + 工具集) → 最终回复
              ↓ 循环调用
         工具执行 → 观察结果 → 继续推理或生成回复
```

单一 LLM (gemini-3-flash-preview) 自主决定工具调用顺序。

### 核心组件

源代码位于 `src/travel_agent/` 目录：

**graph.py** - 图创建入口:
- `create_graph()`: 动态配置模式（推荐），运行时通过 `config["configurable"]` 传递 trip_id/customer_id
- `create_graph_static()`: 静态绑定模式（CLI 兼容），构建时绑定参数
- `get_graph()`: 单例模式（服务端使用）

**state.py** - 简化状态定义:
- 仅保留 `messages`（对话历史）用于 checkpoint 持久化
- trip_id/customer_id/current_date 通过 `config["configurable"]` 传递

**tools/** - 统一工具集（10 个工具）:
- Notion 查询: `query_golf_bookings`, `query_hotel_bookings`, `query_logistics`, `query_itinerary`, `query_customer`
- Notion 更新: `update_dietary_preferences`, `update_handicap`, `update_service_requirements`
- 外部 API: `query_weather`, `search_web`
- 工具通过 `RunnableConfig` 获取 trip_id/customer_id，无需构建时绑定

**prompts.py** - System Prompt:
- `prompt_factory()`: 运行时从 config 动态生成（用 RunnableLambda 包装）
- `create_system_prompt()`: 静态生成（CLI 兼容）
- 包含隐私保护规则：客户模式下禁止透露其他客户信息

**server.py** - FastAPI + LangServe 服务端:
- 通过 HTTP Headers 传递上下文（X-Thread-Id, X-Trip-Id, X-User-Id, X-Date）
- `/agent/invoke` - LangServe 端点
- `/auth/login` - 客户认证端点
- `/welcome` - 欢迎消息端点（需要 `trip_id`, `date` 必填，`customer_id` 可选）
- 使用 AsyncSqliteSaver 进行会话持久化

### Notion 集成

位于 `src/travel_agent/utils/notion/`:

**client.py** - 统一 API 客户端:
- 基于 Notion 2025-09-03 API，使用 `data_source_id` 替代 `database_id`
- TTL 缓存：查询 5 分钟，页面 2 分钟
- 写操作自动失效缓存

**config.py** - 数据库配置:
- `DATABASES`: 数据库 ID 映射（延迟加载）
- `SCHEMAS`: 完整的字段定义，包含 type/key/semantic/relation_target

**types.py** - 属性类型转换:
- `parse_page_properties()`: Notion → Python
- `build_page_properties()`: Python → Notion

### 用户模式

- **管理员模式** (`-u admin`): 访问所有数据，CLI 下显示思维链
- **客户模式** (`-u <page_id>`): 仅访问关联行程，工具自动过滤权限，隐私保护

## 数据流

1. 用户输入问题
2. ReAct Agent 分析问题，决定需要调用哪些工具
3. 工具从 `config["configurable"]` 读取 trip_id，查询 Notion 数据库
4. 基于工具结果生成最终回复

## 入口点

- **main.py** - CLI 模式，支持多轮对话，启动时自动获取今日行程和天气
- **server.py** - FastAPI Server，多租户架构，供前端通过 LangServe 调用
