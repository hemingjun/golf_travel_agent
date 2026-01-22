"""FastAPI Server for Golf Travel Agent

NAS Docker 部署的无头后端服务，供 Vercel 前端通过 langserve 调用。

启动方式:
    TRIP_ID=<行程ID> uv run python -m travel_agent.server
    # 或
    TRIP_ID=<行程ID> uv run uvicorn travel_agent.server:app --host 0.0.0.0 --port 8080
"""

import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langserve import add_routes
from pydantic import BaseModel

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


TRIP_ID = os.getenv("TRIP_ID", "")
if not TRIP_ID:
    raise ValueError("TRIP_ID environment variable is required")

DB_PATH = os.getenv("DB_PATH") or get_default_db_path()

# ==============================================================================
# Pydantic Schemas
# ==============================================================================


class HealthResponse(BaseModel):
    """健康检查响应"""

    status: str
    version: str
    trip_id: str


# ==============================================================================
# FastAPI Application
# ==============================================================================

app = FastAPI(
    title="Golf Travel Agent API",
    version="0.2.0",
    description="高尔夫旅行智能助手 API - NAS Docker 部署版 (langserve)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================================================================
# Shared Graph Instance (SqliteSaver Persistence)
# ==============================================================================

graph = create_graph(
    trip_id=TRIP_ID,
    customer_id="",  # 管理员模式
    current_date=datetime.now().strftime("%Y年%m月%d日"),
    checkpointer="sqlite",
    db_path=DB_PATH,
)

# ==============================================================================
# Routes
# ==============================================================================


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查端点"""
    return HealthResponse(
        status="healthy",
        version="0.2.0",
        trip_id=TRIP_ID[:8] + "..." if len(TRIP_ID) > 8 else TRIP_ID,
    )


# langserve 标准端点: /agent/invoke, /agent/batch, /agent/stream, etc.
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
