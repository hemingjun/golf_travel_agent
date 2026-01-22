"""FastAPI Server for Golf Travel Agent

动态多租户后端服务，供 Vercel 前端通过 langserve 调用。

启动方式:
    uv run python -m travel_agent.server
    # 或
    uv run uvicorn travel_agent.server:app --host 0.0.0.0 --port 8080

客户端请求格式（配置通过 HTTP Headers 传递）:
    POST /agent/invoke
    Headers:
        X-Thread-Id: session_123
        X-Trip-Id: notion-page-id
        X-User-Id: customer-page-id (可选)
        X-Date: 2026年01月22日
    Body:
        {"input": {"messages": [{"role": "user", "content": "今天几点开球？"}]}}
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langserve import add_routes
from pydantic import BaseModel
from starlette.requests import Request

from .graph import create_graph

load_dotenv()

# ==============================================================================
# Configuration
# ==============================================================================


def get_default_db_path() -> str:
    """获取默认数据库路径，自动检测 Docker/本地环境"""
    docker_path = Path("/app/data")
    if docker_path.exists():
        return "/app/data/checkpoints.db"
    # 本地开发：使用项目根目录下的 data 文件夹
    local_path = Path(__file__).parent.parent.parent / "data"
    local_path.mkdir(exist_ok=True)
    return str(local_path / "checkpoints.db")


DB_PATH = os.getenv("DB_PATH") or get_default_db_path()

# ==============================================================================
# Pydantic Schemas
# ==============================================================================


class HealthResponse(BaseModel):
    """健康检查响应"""

    status: str
    version: str


# ==============================================================================
# LangServe Config Modifier
# ==============================================================================


def per_req_config_modifier(config: dict[str, Any], request: Request) -> dict[str, Any]:
    """
    从 HTTP Headers 中提取上下文配置。
    Header 映射规则:
    - X-Thread-Id  -> configurable["thread_id"]
    - X-Trip-Id    -> configurable["trip_id"]
    - X-User-Id    -> configurable["customer_id"]
    - X-Date       -> configurable["current_date"]
    """
    if "configurable" not in config:
        config["configurable"] = {}

    headers = request.headers

    # Thread ID (会话核心)
    if "x-thread-id" in headers:
        config["configurable"]["thread_id"] = headers["x-thread-id"]

    # 业务上下文
    if "x-trip-id" in headers:
        config["configurable"]["trip_id"] = headers["x-trip-id"]
    if "x-user-id" in headers:
        config["configurable"]["customer_id"] = headers["x-user-id"]
    if "x-date" in headers:
        config["configurable"]["current_date"] = headers["x-date"]

    # 调试日志
    print(f"🔧 [Config] Thread: {config['configurable'].get('thread_id')}, Trip: {config['configurable'].get('trip_id')}")

    return config


# ==============================================================================
# FastAPI Application with Lifespan (Async Checkpointer)
# ==============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理 - 初始化 AsyncSqliteSaver"""
    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        # 创建图实例（传入已初始化的 checkpointer）
        graph = create_graph(checkpointer=checkpointer)

        # 注册 LangServe 路由
        add_routes(
            app,
            graph,
            path="/agent",
            enable_feedback_endpoint=True,
            per_req_config_modifier=per_req_config_modifier,
        )

        print(f"🚀 [Server] Graph initialized with AsyncSqliteSaver (db: {DB_PATH})")
        yield
        print("🛑 [Server] Shutting down...")


app = FastAPI(
    title="Golf Travel Agent API",
    version="0.3.0",
    description="高尔夫旅行智能助手 API - 动态多租户架构 (langserve)",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# Routes
# ==============================================================================


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查端点"""
    return HealthResponse(
        status="healthy",
        version="0.3.0",
    )


# ==============================================================================
# Entry Point
# ==============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "travel_agent.server:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
    )
