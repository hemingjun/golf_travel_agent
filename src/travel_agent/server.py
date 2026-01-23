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
from datetime import datetime, timedelta
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
# Environment Validation
# ==============================================================================

REQUIRED_ENV_VARS = ["GOOGLE_API_KEY", "NOTION_TOKEN"]


def _validate_env_vars():
    """验证必需的环境变量是否已设置"""
    missing = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Please set them in .env file or environment."
        )


_validate_env_vars()

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

# 会话上下文缓存：thread_id -> {date, trip_id, customer_id, expires_after}
SESSION_CONTEXT: dict[str, dict] = {}

# 行程会话映射：trip_id -> set[thread_id]（用于批量清理内存缓存）
TRIP_SESSIONS: dict[str, set[str]] = {}

# Welcome 消息缓存：cache_key -> {greeting, customer_name, thread_id, expires_at}
WELCOME_CACHE: dict[str, dict] = {}
WELCOME_CACHE_TTL = timedelta(hours=3)  # 3小时过期


def _get_trip_end_date(trip_id: str) -> str | None:
    """获取行程结束日期 (ISO 格式)"""
    from .utils.notion import get_client

    try:
        client = get_client()
        trip_info = client.get_page(trip_id)
        trip_date_str = trip_info.get("properties", {}).get("项目日期", "")
        if "→" in str(trip_date_str):
            return str(trip_date_str).split("→")[1].strip()
    except Exception:
        pass
    return None


def _cleanup_trip_sessions(trip_id: str) -> int:
    """清理指定行程的所有内存缓存

    Returns: 清理的会话数量
    """
    if trip_id not in TRIP_SESSIONS:
        return 0

    thread_ids = TRIP_SESSIONS.pop(trip_id)
    count = 0

    for thread_id in thread_ids:
        SESSION_CONTEXT.pop(thread_id, None)
        count += 1

    print(f"🗑️ [Cleanup] Trip {trip_id[:8]}... ended, cleaned {count} session(s)")
    return count


def _cleanup_expired_sessions() -> int:
    """清理所有过期会话（行程结束 3 天后）

    Returns: 清理的会话总数
    """
    from datetime import datetime, timedelta

    today = datetime.now().date()
    expired_trips: list[str] = []

    # 收集过期的行程
    for trip_id in list(TRIP_SESSIONS.keys()):
        # 从该行程的任一会话获取 expires_after
        thread_ids = TRIP_SESSIONS.get(trip_id, set())
        if not thread_ids:
            continue

        sample_thread_id = next(iter(thread_ids))
        ctx = SESSION_CONTEXT.get(sample_thread_id, {})
        expires_after = ctx.get("expires_after")

        if expires_after:
            try:
                trip_end = datetime.strptime(expires_after, "%Y-%m-%d").date()
                cleanup_date = trip_end + timedelta(days=3)
                if today > cleanup_date:
                    expired_trips.append(trip_id)
            except ValueError:
                pass

    # 批量清理
    total_cleaned = 0
    for trip_id in expired_trips:
        total_cleaned += _cleanup_trip_sessions(trip_id)

    return total_cleaned


async def _daily_cleanup_task():
    """每日定时清理任务（凌晨 3 点执行）"""
    import asyncio
    from datetime import datetime, time, timedelta

    while True:
        # 计算距离下次凌晨 3 点的秒数
        now = datetime.now()
        target_time = time(3, 0, 0)  # 凌晨 3 点
        target_datetime = datetime.combine(now.date(), target_time)

        if now.time() >= target_time:
            # 今天的 3 点已过，等到明天
            target_datetime += timedelta(days=1)

        wait_seconds = (target_datetime - now).total_seconds()
        print(f"🕐 [Cleanup] Next cleanup scheduled at {target_datetime}, waiting {wait_seconds:.0f}s")

        await asyncio.sleep(wait_seconds)

        # 执行清理
        cleaned = _cleanup_expired_sessions()
        print(
            f"🧹 [Cleanup] Daily cleanup completed: {cleaned} session(s) removed, "
            f"{len(SESSION_CONTEXT)} remaining"
        )


# ==============================================================================
# Welcome Cache Helpers
# ==============================================================================


def _get_welcome_cache_key(trip_id: str, customer_id: str, date: str) -> str:
    """生成 welcome 缓存 key

    customer_id 为 "admin" 时表示管理员模式
    """
    return f"{trip_id}:{customer_id}:{date}"


def _get_welcome_from_cache(cache_key: str) -> dict | None:
    """从缓存获取 welcome 数据，过期则返回 None"""
    if cache_key not in WELCOME_CACHE:
        return None

    cached = WELCOME_CACHE[cache_key]
    if datetime.now() > cached["expires_at"]:
        # 过期，删除缓存
        del WELCOME_CACHE[cache_key]
        return None

    return cached


def _set_welcome_cache(
    cache_key: str,
    greeting: str,
    customer_name: str,
    thread_id: str,
) -> None:
    """设置 welcome 缓存"""
    WELCOME_CACHE[cache_key] = {
        "greeting": greeting,
        "customer_name": customer_name,
        "thread_id": thread_id,
        "expires_at": datetime.now() + WELCOME_CACHE_TTL,
    }


# ==============================================================================
# Pydantic Schemas
# ==============================================================================


class HealthResponse(BaseModel):
    """健康检查响应"""

    status: str
    version: str


class LoginRequest(BaseModel):
    """客户登录请求"""

    full_name: str  # 全名拼音 (Last, First)
    birthday: str  # 生日 YYYY-MM-DD
    trip_id: str  # 行程 ID


class LoginResponse(BaseModel):
    """客户登录响应"""

    success: bool
    customer_id: str | None = None
    customer_name: str | None = None
    error: str | None = None


class WelcomeRequest(BaseModel):
    """欢迎接口请求"""

    trip_id: str
    customer_id: str  # 必填，"admin" = 管理员模式，其他值 = 客户 Page ID
    date: str  # 必填，格式 YYYY-MM-DD，由前端传递目的地时区的日期


class WelcomeResponse(BaseModel):
    """欢迎接口响应"""

    success: bool
    customer_name: str = ""
    greeting: str = ""
    thread_id: str = ""  # 用于后续对话
    error: str | None = None


# ==============================================================================
# LangServe Config Modifier
# ==============================================================================


def per_req_config_modifier(config: dict[str, Any], request: Request) -> dict[str, Any]:
    """
    从 HTTP Headers 中提取上下文配置，支持从 SESSION_CONTEXT 缓存补充。
    优先级: Header > 缓存

    注：过期清理由后台定时任务处理，此处只做缓存查找。
    """
    if "configurable" not in config:
        config["configurable"] = {}

    headers = request.headers
    thread_id = headers.get("x-thread-id")

    # Thread ID (会话核心)
    if thread_id:
        config["configurable"]["thread_id"] = thread_id

        # 从缓存补充上下文（如果 Header 未提供）
        if thread_id in SESSION_CONTEXT:
            ctx = SESSION_CONTEXT[thread_id]
            if "x-date" not in headers and ctx.get("date"):
                config["configurable"]["current_date"] = ctx["date"]
            if "x-trip-id" not in headers and ctx.get("trip_id"):
                config["configurable"]["trip_id"] = ctx["trip_id"]
            if "x-user-id" not in headers and ctx.get("customer_id"):
                config["configurable"]["customer_id"] = ctx["customer_id"]

    # Header 优先（覆盖缓存）
    if "x-trip-id" in headers:
        config["configurable"]["trip_id"] = headers["x-trip-id"]
    if "x-user-id" in headers:
        config["configurable"]["customer_id"] = headers["x-user-id"]
    if "x-date" in headers:
        config["configurable"]["current_date"] = headers["x-date"]

    # 调试日志
    cache_hit = thread_id and thread_id in SESSION_CONTEXT
    print(
        f"🔧 [Config] Thread: {config['configurable'].get('thread_id', 'N/A')[:8]}..., "
        f"Trip: {config['configurable'].get('trip_id', 'N/A')[:8]}..., "
        f"Cache: {'hit' if cache_hit else 'miss'}"
    )

    return config


# ==============================================================================
# FastAPI Application with Lifespan (Async Checkpointer)
# ==============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理 - 初始化 AsyncSqliteSaver 和定时清理任务"""
    import asyncio

    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        # 创建图实例（传入已初始化的 checkpointer）
        graph = create_graph(checkpointer=checkpointer)

        # 保存 graph 到 app.state，供 /welcome 端点使用
        app.state.graph = graph

        # 注册 LangServe 路由
        add_routes(
            app,
            graph,
            path="/agent",
            enable_feedback_endpoint=True,
            per_req_config_modifier=per_req_config_modifier,
        )

        # 启动每日清理任务
        cleanup_task = asyncio.create_task(_daily_cleanup_task())

        print(f"🚀 [Server] Graph initialized with AsyncSqliteSaver (db: {DB_PATH})")
        yield

        # 关闭时取消清理任务
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
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


@app.post("/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """客户认证端点 - 通过全名+生日验证客户身份

    前端调用此端点获取 customer_id，之后在对话请求中通过 X-User-Id Header 传递。
    """
    from .tools.customer import authenticate_customer

    result = authenticate_customer(
        full_name=request.full_name,
        birthday=request.birthday,
        trip_id=request.trip_id,
    )

    if result:
        return LoginResponse(
            success=True,
            customer_id=result.get("id"),
            customer_name=result.get("name"),
        )
    return LoginResponse(success=False, error="认证失败：姓名或生日不匹配")


def _format_date_cn(date_iso: str) -> str:
    """将 ISO 日期转换为中文格式"""
    from datetime import datetime

    dt = datetime.strptime(date_iso, "%Y-%m-%d")
    return dt.strftime("%Y年%m月%d日")


def _extract_text_content(content) -> str:
    """从 LLM 响应中提取纯文本（兼容 Gemini 多模态格式）"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
            elif isinstance(item, str):
                texts.append(item)
        return "\n".join(texts)
    return str(content)


def _get_trip_location(trip_id: str) -> str:
    """从行程中提取位置信息（返回第一个酒店或球场地址）

    行程目的地通常固定，直接返回第一个酒店/球场地址即可。
    """
    from .tools._utils import _extract_text
    from .utils.notion import DATABASES, get_client

    client = get_client()
    default_location = "Los Cabos, Mexico"

    # 1. 优先查询酒店地址
    try:
        hotel_bookings = client.query_pages(
            DATABASES["酒店组件"],
            filter={"property": "关联行程", "relation": {"contains": trip_id}},
            sorts=[{"property": "入住日期", "direction": "ascending"}],
        )

        if hotel_bookings:
            hotel_ids = hotel_bookings[0].get("properties", {}).get("酒店", [])
            if hotel_ids:
                hotel_page = client.get_page(hotel_ids[0])
                address = _extract_text(hotel_page.get("properties", {}).get("地址", ""))
                if address:
                    print(f"[Location] 使用酒店地址")
                    return address
    except Exception as e:
        print(f"[Location] 查询酒店失败: {e}")

    # 2. 备选：查询球场地址
    try:
        golf_bookings = client.query_pages(
            DATABASES["高尔夫组件"],
            filter={"property": "关联行程", "relation": {"contains": trip_id}},
            sorts=[{"property": "PlayDate", "direction": "ascending"}],
        )

        if golf_bookings:
            address = _extract_text(golf_bookings[0].get("properties", {}).get("地址", ""))
            if address:
                print(f"[Location] 使用球场地址")
                return address
    except Exception as e:
        print(f"[Location] 查询球场失败: {e}")

    print(f"[Location] 使用默认地址")
    return default_location


def _get_trip_start_date(trip_id: str) -> str | None:
    """获取行程开始日期 (ISO 格式)"""
    from .utils.notion import get_client

    try:
        client = get_client()
        trip_info = client.get_page(trip_id)
        trip_date_str = trip_info.get("properties", {}).get("项目日期", "")

        # 解析行程开始日期（格式: "2026-01-27 → 2026-02-02" 或单个日期）
        if "→" in str(trip_date_str):
            return str(trip_date_str).split("→")[0].strip()
        elif trip_date_str:
            return str(trip_date_str).strip()
    except Exception as e:
        print(f"[TripDate] 获取行程日期失败: {e}")

    return None


@app.post("/welcome", response_model=WelcomeResponse)
async def welcome(request: Request, body: WelcomeRequest):
    """获取今日行程和天气，调用 LLM 生成欢迎消息

    复用 main.py 的逻辑：
    1. 直接调用工具获取数据（避免 Agent 推理延迟）
    2. 构建 greeting_prompt 注入数据
    3. 调用 graph.invoke 生成欢迎语
    """
    import uuid
    from datetime import datetime

    from langchain_core.messages import HumanMessage

    from .tools.customer import get_customer_info
    from .tools.itinerary import query_itinerary
    from .tools.weather import query_weather

    # 0. 验证日期格式
    try:
        datetime.strptime(body.date, "%Y-%m-%d")
    except ValueError:
        return WelcomeResponse(
            success=False,
            error=f"日期格式错误: {body.date}，应为 YYYY-MM-DD",
        )

    # 0.5 检查缓存
    cache_key = _get_welcome_cache_key(body.trip_id, body.customer_id, body.date)
    cached = _get_welcome_from_cache(cache_key)
    if cached:
        print(f"✅ [Welcome] Cache hit: {cache_key}")
        return WelcomeResponse(
            success=True,
            customer_name=cached["customer_name"],
            greeting=cached["greeting"],
            thread_id=cached["thread_id"],
        )

    # 使用前端传递的日期
    today_iso = body.date
    current_date = _format_date_cn(body.date)

    # 1. 获取客户信息 (customer_id="admin" 表示管理员模式)
    customer_name = "管理员"
    customer_info = None
    is_admin = body.customer_id.lower() == "admin"
    if not is_admin:
        customer_info = get_customer_info(body.customer_id)
        if customer_info:
            customer_name = customer_info.get("name", "客户")

    # 2. 构建 config
    thread_id = str(uuid.uuid4())

    # 获取行程结束日期用于缓存过期
    trip_end_date = _get_trip_end_date(body.trip_id)

    # 缓存会话上下文，供后续 /agent/invoke 使用
    SESSION_CONTEXT[thread_id] = {
        "date": current_date,  # 中文格式
        "trip_id": body.trip_id,
        "customer_id": body.customer_id,
        "expires_after": trip_end_date,  # 行程结束日期，用于过期清理
    }

    # 注册到行程会话映射（用于批量清理）
    if body.trip_id not in TRIP_SESSIONS:
        TRIP_SESSIONS[body.trip_id] = set()
    TRIP_SESSIONS[body.trip_id].add(thread_id)

    config = {
        "configurable": {
            "thread_id": thread_id,
            "trip_id": body.trip_id,
            "customer_id": body.customer_id,
            "customer_info": customer_info,
            "current_date": current_date,
        }
    }

    # 3. 获取行程数据
    try:
        itinerary_data = query_itinerary.invoke({}, config=config)
        print(f"📋 [Welcome] itinerary_data: {str(itinerary_data)[:200]}")
    except Exception as e:
        itinerary_data = f"行程数据获取失败: {e}"
        print(f"❌ [Welcome] itinerary error: {e}")

    # 4. 自动获取位置并查询天气
    location = _get_trip_location(body.trip_id)
    print(f"📍 [Welcome] location: {location}")

    # 确定天气查询日期
    trip_start = _get_trip_start_date(body.trip_id)
    if trip_start and today_iso < trip_start:
        # 行程未开始：检查是否在 10 天内
        days_until_trip = (datetime.strptime(trip_start, "%Y-%m-%d") -
                          datetime.strptime(today_iso, "%Y-%m-%d")).days
        if days_until_trip <= 10:
            weather_date = trip_start  # 10天内可预报，查行程第一天
            print(f"🗓️ [Welcome] 行程未开始，{days_until_trip}天后出发，查询行程首日天气: {weather_date}")
        else:
            weather_date = today_iso  # 超过10天，查当天（无法预报那么远）
            print(f"🗓️ [Welcome] 行程未开始，{days_until_trip}天后出发，查询当天天气: {weather_date}")
    else:
        weather_date = today_iso  # 行程已开始，用前端日期
        print(f"🗓️ [Welcome] 行程进行中，查询当天天气: {weather_date}")

    try:
        weather_data = query_weather.invoke({"location": location, "date": weather_date})
        print(f"🌤️ [Welcome] weather_data: {str(weather_data)[:200]}")
    except Exception as e:
        weather_data = f"天气数据获取失败: {e}"
        print(f"❌ [Welcome] weather error: {e}")

    # 5. 构建 greeting_prompt（明确日期信息 + 详细服务介绍）
    # 格式化行程开始日期为中文
    trip_start_cn = _format_date_cn(trip_start) if trip_start else "未知"
    weather_date_cn = _format_date_cn(weather_date)
    weather_type = "行程首日预报" if weather_date != today_iso else "当天天气"
    # 简化地点显示
    location_short = location[:50] + "..." if len(location) > 50 else location

    greeting_prompt = f"""[系统指令] 为 {customer_name} 生成欢迎语

## 关键时间信息
- 今天日期: {current_date}
- 行程开始日期: {trip_start_cn}
- 天气查询日期: {weather_date_cn}（{weather_type}）

## 行程数据
{itinerary_data}

## 天气数据（{weather_date_cn} @ {location_short}）
{weather_data}

## 生成要求
1. 直接用名字称呼，不用"先生"、"女士"
2. 明确说明今天是 {current_date}，{"行程即将在 " + trip_start_cn + " 开始" if today_iso < (trip_start or today_iso) else "行程进行中"}
3. 天气提醒必须包含具体日期（{weather_date_cn}）和地点
4. 服务介绍要具体说明助手能做什么：
   - 查询每日行程安排、酒店和球场信息
   - 实时天气预报
   - 球场攻略和打球建议
   - 记录个人偏好（饮食忌口、高尔夫差点等）
   - 协调接送和特殊服务需求

注意：直接生成回复，不需要调用工具。"""

    # 6. 调用 Self-Healing LLM 生成欢迎语
    try:
        from .llm_wrapper import create_self_healing_llm

        llm = create_self_healing_llm(
            model="gemini-3-flash-preview",
            temperature=0.3,
            request_timeout=30,
            max_retries=2,
        )
        response = await llm.ainvoke([HumanMessage(content=greeting_prompt)])

        # 调试日志
        content = response.content
        content_preview = str(content)[:200] if content else "EMPTY"
        print(f"🔍 [Welcome] LLM response type: {type(content).__name__}, preview: {content_preview}")

        greeting = _extract_text_content(content)
    except Exception as e:
        return WelcomeResponse(
            success=False,
            error=f"生成欢迎消息失败: {e}",
        )

    # 验证 greeting 内容有效性（不缓存空内容）
    if not greeting or not greeting.strip():
        print(f"⚠️ [Welcome] Empty greeting, skipping cache")
        return WelcomeResponse(
            success=False,
            error="生成欢迎消息失败：LLM 返回空内容",
        )

    # 写入缓存（仅缓存有效内容）
    _set_welcome_cache(cache_key, greeting, customer_name, thread_id)
    print(f"📝 [Welcome] Cache set: {cache_key}, expires in 3h")

    return WelcomeResponse(
        success=True,
        customer_name=customer_name,
        greeting=greeting,
        thread_id=thread_id,
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
