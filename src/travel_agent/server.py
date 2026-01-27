"""FastAPI Server for Golf Travel Agent

动态多租户后端服务，供前端通过 LangServe 调用。

启动方式:
    uv run python -m travel_agent.server
    uv run uvicorn travel_agent.server:app --host 0.0.0.0 --port 8080
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import time as dt_time, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langserve import add_routes
from starlette.requests import Request

from .api import (
    CustomerTripInfo,
    CustomerTripsResponse,
    HealthResponse,
    LoginRequest,
    LoginResponse,
    TripInfo,
    UpcomingTripsResponse,
    WelcomeRequest,
    WelcomeResponse,
)
from .cache import cache_manager
from .graph import create_graph
from .services import WelcomeService

load_dotenv()

# =============================================================================
# 环境验证
# =============================================================================

REQUIRED_ENV_VARS = ["GOOGLE_API_KEY", "NOTION_TOKEN"]


def _validate_env_vars():
    missing = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")


_validate_env_vars()

# =============================================================================
# 配置
# =============================================================================


def get_default_db_path() -> str:
    docker_path = Path("/app/data")
    if docker_path.exists():
        return "/app/data/checkpoints.db"
    local_path = Path(__file__).parent.parent.parent / "data"
    local_path.mkdir(exist_ok=True)
    return str(local_path / "checkpoints.db")


DB_PATH = os.getenv("DB_PATH") or get_default_db_path()

# =============================================================================
# LangServe Config Modifier
# =============================================================================


def per_req_config_modifier(config: dict[str, Any], request: Request) -> dict[str, Any]:
    """从 HTTP Headers 中提取上下文配置"""
    if "configurable" not in config:
        config["configurable"] = {}

    headers = request.headers
    thread_id = headers.get("x-thread-id")

    if thread_id:
        config["configurable"]["thread_id"] = thread_id
        # 从缓存补充上下文
        ctx = cache_manager.get_session(thread_id)
        if ctx:
            if "x-date" not in headers and ctx.get("date"):
                config["configurable"]["current_date"] = ctx["date"]
            if "x-trip-id" not in headers and ctx.get("trip_id"):
                config["configurable"]["trip_id"] = ctx["trip_id"]
            if "x-user-id" not in headers and ctx.get("customer_id"):
                config["configurable"]["customer_id"] = ctx["customer_id"]

    # Header 优先
    if "x-trip-id" in headers:
        config["configurable"]["trip_id"] = headers["x-trip-id"]
    if "x-user-id" in headers:
        config["configurable"]["customer_id"] = headers["x-user-id"]
    if "x-date" in headers:
        config["configurable"]["current_date"] = headers["x-date"]

    return config


# =============================================================================
# 定时清理任务
# =============================================================================


async def _daily_cleanup_task():
    """每日凌晨 3 点执行清理"""
    while True:
        now = datetime.now()
        target_time = dt_time(3, 0, 0)
        target_datetime = datetime.combine(now.date(), target_time)
        if now.time() >= target_time:
            target_datetime += timedelta(days=1)
        wait_seconds = (target_datetime - now).total_seconds()
        await asyncio.sleep(wait_seconds)
        cleaned = cache_manager.cleanup_expired_sessions()
        stats = cache_manager.stats()
        print(f"[Cleanup] Daily cleanup: {cleaned} sessions removed, {stats['session_count']} remaining")


# =============================================================================
# FastAPI 应用
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        graph = create_graph(checkpointer=checkpointer)
        app.state.graph = graph

        add_routes(
            app,
            graph,
            path="/agent",
            enable_feedback_endpoint=True,
            per_req_config_modifier=per_req_config_modifier,
        )

        cleanup_task = asyncio.create_task(_daily_cleanup_task())
        print(f"[Server] Graph initialized (db: {DB_PATH})")
        yield

        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass

        from .tools._weather_api import close_async_client
        await close_async_client()
        print("[Server] Shutting down...")


app = FastAPI(
    title="Golf Travel Agent API",
    version="0.4.0",
    description="高尔夫旅行智能助手 API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# 路由端点
# =============================================================================


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查"""
    return HealthResponse(status="healthy", version="0.4.0")


@app.post("/cache/clear-welcome")
async def clear_welcome_cache():
    """清空 Welcome 消息缓存"""
    count = cache_manager.clear_welcome_cache()
    return {"success": True, "cleared": count}


@app.get("/cache/stats")
async def cache_stats():
    """获取缓存统计"""
    return cache_manager.stats()


@app.post("/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """客户认证"""
    # Admin 快捷登录
    if request.full_name.lower() == "admin":
        cache_manager.invalidate_on_login()
        return LoginResponse(success=True, customer_id="admin", customer_name="管理员")

    if not request.birthday:
        return LoginResponse(success=False, error="请提供生日")

    from .tools.customer import authenticate_customer_global

    result = authenticate_customer_global(
        full_name=request.full_name,
        birthday=request.birthday,
    )

    if result:
        cache_manager.invalidate_on_login()
        return LoginResponse(
            success=True,
            customer_id=result.get("id"),
            customer_name=result.get("name"),
        )
    return LoginResponse(success=False, error="未找到匹配的用户信息")


@app.get("/trips/upcoming", response_model=UpcomingTripsResponse)
async def get_upcoming_trips():
    """获取即将开始或正在进行的行程列表"""
    from .utils.notion import DATABASES, get_client

    try:
        client = get_client()
        trips = client.query_pages(
            DATABASES["行程"],
            filter={
                "or": [
                    {"property": "项目状态", "formula": {"string": {"equals": "未开始"}}},
                    {"property": "项目状态", "formula": {"string": {"equals": "进行中"}}},
                ]
            },
            sorts=[{"property": "项目日期", "direction": "ascending"}],
        )

        result = []
        for trip in trips:
            props = trip.get("properties", {})
            trip_name = props.get("Name", "") or ""

            start_date = None
            end_date = None
            date_val = props.get("项目日期")
            if date_val:
                if hasattr(date_val, "isoformat"):
                    start_date = date_val.isoformat()
                    end_date = start_date
                elif isinstance(date_val, str):
                    start_date = date_val
                    end_date = date_val

            status = props.get("项目状态", "") or ""
            customer_ids = props.get("客户", []) or []
            customer_count = len(customer_ids) if isinstance(customer_ids, list) else 0

            result.append(
                TripInfo(
                    trip_id=trip.get("id", ""),
                    trip_name=trip_name,
                    start_date=start_date,
                    end_date=end_date,
                    status=status,
                    customer_count=customer_count,
                )
            )

        return UpcomingTripsResponse(success=True, trips=result)
    except Exception as e:
        return UpcomingTripsResponse(success=False, error=str(e))


@app.get("/customers/{customer_id}/trips", response_model=CustomerTripsResponse)
async def get_customer_trips(customer_id: str):
    """获取客户参加的所有行程"""
    from .utils.notion import DATABASES, get_client

    client = get_client()

    def _map_status(notion_status: str) -> str:
        return {"未开始": "upcoming", "进行中": "ongoing", "已结束": "completed"}.get(notion_status, "upcoming")

    def _sort_key(trip: CustomerTripInfo) -> tuple:
        priority = {"ongoing": 0, "upcoming": 1, "completed": 2}.get(trip.status, 3)
        return (priority, trip.start_date or "9999-99-99")

    # Admin 模式
    if not customer_id or customer_id.lower() == "admin":
        try:
            all_trips = client.query_pages(
                DATABASES["行程"],
                filter={
                    "or": [
                        {"property": "项目状态", "formula": {"string": {"equals": "未开始"}}},
                        {"property": "项目状态", "formula": {"string": {"equals": "进行中"}}},
                    ]
                },
                sorts=[{"property": "项目日期", "direction": "ascending"}],
            )

            trips = []
            for trip in all_trips:
                trip_id = trip.get("id", "")
                trip_props = trip.get("properties", {})
                trip_name = trip_props.get("Name", "") or ""

                start_date = None
                date_val = trip_props.get("项目日期")
                if date_val:
                    if hasattr(date_val, "isoformat"):
                        start_date = date_val.isoformat()
                    elif isinstance(date_val, str):
                        start_date = date_val

                notion_status = trip_props.get("项目状态", "") or ""
                destination = WelcomeService.get_trip_destination(trip_id)

                trips.append(
                    CustomerTripInfo(
                        id=trip_id,
                        name=trip_name,
                        destination=destination,
                        start_date=start_date,
                        end_date=start_date,
                        status=_map_status(notion_status),
                    )
                )

            trips.sort(key=_sort_key)
            return CustomerTripsResponse(success=True, trips=trips)
        except Exception as e:
            return CustomerTripsResponse(success=False, error=f"获取行程列表失败: {e}")

    # 普通客户
    try:
        customer_page = client.get_page(customer_id)
        props = customer_page.get("properties", {})
        trip_ids = props.get("参加的行程", [])

        if not trip_ids:
            return CustomerTripsResponse(success=True, trips=[])

        trips = []
        for trip_id in trip_ids:
            try:
                trip_page = client.get_page(trip_id)
                trip_props = trip_page.get("properties", {})
                trip_name = trip_props.get("Name", "") or ""

                start_date = None
                date_val = trip_props.get("项目日期")
                if date_val:
                    if hasattr(date_val, "isoformat"):
                        start_date = date_val.isoformat()
                    elif isinstance(date_val, str):
                        start_date = date_val

                notion_status = trip_props.get("项目状态", "") or ""
                destination = WelcomeService.get_trip_destination(trip_id)

                trips.append(
                    CustomerTripInfo(
                        id=trip_id,
                        name=trip_name,
                        destination=destination,
                        start_date=start_date,
                        end_date=start_date,
                        status=_map_status(notion_status),
                    )
                )
            except Exception as e:
                print(f"[CustomerTrips] 获取行程 {trip_id} 失败: {e}")

        trips.sort(key=_sort_key)
        return CustomerTripsResponse(success=True, trips=trips)
    except Exception as e:
        return CustomerTripsResponse(success=False, error=f"获取行程列表失败: {e}")


@app.post("/welcome", response_model=WelcomeResponse)
async def welcome(body: WelcomeRequest):
    """获取今日行程和天气，生成欢迎消息"""
    result = await WelcomeService.generate_greeting(
        trip_id=body.trip_id,
        customer_id=body.customer_id,
        date=body.date,
    )
    return WelcomeResponse(**result)


# =============================================================================
# 入口点
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "travel_agent.server:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
    )
