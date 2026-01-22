"""FastAPI Server for Golf Travel Agent

动态多租户后端服务，供 Vercel 前端通过 langserve 调用。

启动方式:
    uv run python -m travel_agent.server
    # 或
    uv run uvicorn travel_agent.server:app --host 0.0.0.0 --port 8080

客户端请求格式（trip_id/customer_id 通过 config 传递）:
    POST /agent/invoke
    {
        "input": {"messages": [{"role": "user", "content": "今天几点开球？"}]},
        "config": {
            "configurable": {
                "thread_id": "session_123",
                "trip_id": "notion-page-id",
                "customer_id": "",
                "current_date": "2026年01月22日"
            }
        }
    }
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langserve import add_routes
from pydantic import BaseModel

from .graph import get_graph

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
# FastAPI Application
# ==============================================================================

app = FastAPI(
    title="Golf Travel Agent API",
    version="0.3.0",
    description="高尔夫旅行智能助手 API - 动态多租户架构 (langserve)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================================================================
# Shared Graph Instance (动态配置，SqliteSaver 持久化)
# ==============================================================================

# 单例图实例 - trip_id/customer_id 在运行时通过 config["configurable"] 传递
graph = get_graph(checkpointer="sqlite", db_path=DB_PATH)

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


# langserve 标准端点: /agent/invoke, /agent/batch, /agent/stream, etc.
# 客户端需要在 config["configurable"] 中传递 trip_id, customer_id, current_date
add_routes(
    app,
    graph,
    path="/agent",
    enable_feedback_endpoint=True,
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
