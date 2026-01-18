# Golf Travel Agent

## 项目概述
基于 LangGraph 构建的多 Agent 高尔夫旅行智能助手，通过 Notion 管理行程数据。

## 技术栈
- Python 3.11+
- uv (包管理)
- LangGraph (Agent 框架)
- LangChain Google Gemini (LLM 集成，Pro + Flash 双模型)
- Pydantic (数据模型)

## 项目结构
```
src/golf_agent/
├── __init__.py
├── graph/           # LangGraph 图
│   ├── state.py     # 状态定义 + Reducer
│   └── graph.py     # 图构建
├── agents/          # Agent 节点
│   ├── supervisor.py
│   ├── golf.py
│   ├── hotel.py
│   ├── logistics.py
│   ├── itinerary.py
│   ├── customer.py
│   ├── weather.py
│   └── responder.py
├── tools/           # 工具函数
└── notion/          # Notion API 封装
```

## 运行方式
```bash
# 设置环境变量
export GOOGLE_API_KEY=xxx
export NOTION_TOKEN=xxx
export NOTION_DB_GOLF=xxx
export NOTION_DB_HOTEL=xxx
export NOTION_DB_LOGISTIC=xxx
export NOTION_DB_ITINERARY=xxx
export NOTION_DB_CUSTOMER=xxx
export OPENWEATHER_API_KEY=xxx  # 天气 API (可选)

# 管理员模式运行
uv run python main.py -t <行程ID> -u admin

# 客户模式运行（user-id 为客户 page_id）
uv run python main.py -t <行程ID> -u <客户PageID>
```
