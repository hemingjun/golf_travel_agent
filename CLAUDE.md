# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

基于 LangGraph 构建的多 Agent 高尔夫旅行智能助手，通过 Notion 管理行程数据。支持管理员和客户两种模式。

## 常用命令

```bash
# 运行程序
uv run python main.py -t <行程ID> -u admin       # 管理员模式
uv run python main.py -t <行程ID> -u <客户PageID> # 客户模式
uv run python main.py -t <行程ID> -u admin -d    # 开启调试显示思维链

# 开发工具
uv run pytest                    # 运行测试
uv run ruff check .              # 代码检查
uv run ruff format .             # 代码格式化
```

## 环境变量

必需: `GOOGLE_API_KEY`, `NOTION_TOKEN`, `NOTION_DB_GOLF`, `NOTION_DB_HOTEL`, `NOTION_DB_LOGISTIC`, `NOTION_DB_ITINERARY`, `NOTION_DB_CUSTOMER`

可选: `OPENWEATHER_API_KEY`

## 架构

### 图执行流程

```
User → Planner → Supervisor ⇄ Workers → Analyst → Responder → User
                    ↑____________↩
```

入口为 Planner，出口为 Responder，Supervisor 负责循环调度 Workers。

### 双模型策略

- **Smart LLM** (`gemini-2.5-pro`): Planner、Analyst - 负责意图理解和综合分析
- **Fast LLM** (`gemini-2.5-flash`): Supervisor、Responder、部分 Workers - 负责路由和执行

### 核心组件

**graph/state.py** - GraphState 定义，使用 TypedDict + Annotated 实现 Reducer:
- `messages`: 对话历史（add_messages reducer）
- `trip_data`: 结构化数据暂存区（merge_trip_data reducer - 增量合并）
- `route_history`: 路由历史，用于死锁检测（保留最近 10 条）

**agents/planner.py** - 意图精炼与任务拆解:
- 输出 `RefinedPlan` 结构：包含 `data_source`（PUBLIC_WEB/PRIVATE_DB/MIXED）、`task_sequence`、`procurement_recipe`
- 使用字段归属表（FIELD_OWNERSHIP_MAP）进行数据溯源

**agents/supervisor.py** - 智能路由器，实现三大原则:
- Principle A: 强制执行 Planner 的 data_source 指令
- Principle B: 快速失败机制（Worker 返回 FAILURE 时切换）
- Principle C: 动态死锁检测（连续调用+相同哈希）

**Workers** - 无状态数据获取节点:
- `golf_agent`, `hotel_agent`, `logistics_agent`, `itinerary_agent`, `customer_agent`: 内部数据库 Agent
- `weather_agent`: 天气查询
- `search_agent`: 互联网搜索

### Notion 集成

**notion/client.py** - 统一 API 客户端，基于 Notion 2025-09-03 API:
- 使用 `data_source_id` 替代 `database_id`
- 自动处理属性解析和构建（types.py）
- Schema 预定义和缓存（config.py）

### 状态管理

使用 LangGraph MemorySaver 实现多轮对话。关键 reducer:
- `merge_trip_data`: 列表按 ID 去重合并，支持增量更新
- `reset_or_increment`: 迭代计数器，支持重置（防止无限循环）
- `append_route_history`: 追加路由历史，支持哈希更新

## 数据流

1. **Planner** 分析用户意图，生成 `refined_plan`（包含 task_sequence）
2. **Supervisor** 解析 task_sequence，按序路由到对应 Worker
3. **Worker** 执行工具调用，结果存入 `trip_data`
4. **Supervisor** 检查任务完成度，决定继续执行或路由到 Analyst
5. **Analyst** 汇总 trip_data 生成分析报告
6. **Responder** 基于分析报告生成最终回复
