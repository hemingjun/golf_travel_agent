# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

基于 LangGraph ReAct Agent 构建的高尔夫旅行智能助手，通过 Notion 管理行程数据。支持 CLI 和 Chainlit Web UI 两种界面，管理员和客户两种用户模式。

## 常用命令

```bash
# CLI 模式
uv run python main.py -t <行程ID> -u admin       # 管理员模式
uv run python main.py -t <行程ID> -u <客户PageID> # 客户模式
uv run python main.py -t <行程ID> -u admin -d    # 开启调试显示思维链

# Web UI 模式 (Chainlit)
TRIP_ID=<行程ID> uv run chainlit run app.py -w   # 启动 Web 界面

# 开发工具
uv run pytest                    # 运行测试
uv run ruff check .              # 代码检查
uv run ruff format .             # 代码格式化
```

## 环境变量

必需: `GOOGLE_API_KEY`, `NOTION_TOKEN`, `NOTION_DB_GOLF`, `NOTION_DB_HOTEL`, `NOTION_DB_LOGISTIC`, `NOTION_DB_ITINERARY`, `NOTION_DB_CUSTOMER`

可选: `OPENWEATHER_API_KEY`, `TRIP_ID`（Web 模式）

## 架构

### ReAct Agent 模式

```text
用户输入 → ReAct Agent (LLM + 工具集) → 最终回复
              ↓ 循环调用
         工具执行 → 观察结果 → 继续推理或生成回复
```

单一 LLM 自主决定工具调用顺序，取代原有的多 Agent DAG 架构。

### 核心组件

**graph/react_graph.py** - 图创建入口:

- `create_react_graph()`: 创建 ReAct Agent，注入 trip_id/customer_id
- 使用 `langgraph.prebuilt.create_react_agent`

**graph/react_state.py** - 简化状态定义:

- `messages`: 对话历史（add_messages reducer）
- `trip_id`, `customer_id`: 上下文标识
- `current_date`: 当前日期（用于相对日期计算）
- `customer_info`: 客户信息缓存

**tools/unified_tools.py** - 统一工具集（7 个工具）:

- 内部数据库: `query_golf_bookings`, `query_hotel_bookings`, `query_logistics`, `query_itinerary`, `query_customer`
- 外部 API: `query_weather`, `search_web`
- 闭包模式注入 trip_id/customer_id，客户模式自动权限过滤

**prompts/react_prompt.py** - System Prompt:

- 事实优先原则（禁止猜测，必须调用工具）
- 工具调用策略和日期处理规则
- 回答风格指导

### Notion 集成

**notion/client.py** - 统一 API 客户端，基于 Notion 2025-09-03 API:
- 使用 `data_source_id` 替代 `database_id`
- 自动处理属性解析和构建（types.py）
- Schema 预定义和缓存（config.py）

### 用户模式

- **管理员模式** (`-u admin`): 访问所有数据，显示完整思维链
- **客户模式** (`-u <page_id>`): 仅访问关联行程，工具自动过滤权限

## 数据流

1. 用户输入问题
2. ReAct Agent 分析问题，决定需要调用哪些工具
3. 并行/串行调用工具获取数据（工具返回格式化文本）
4. 基于工具结果生成最终回复

## 入口点

- **main.py** - CLI 模式，支持多轮对话
- **app.py** - Chainlit Web UI，包含登录验证流程（全名拼音+生日）
