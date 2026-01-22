"""FastAPI Server for Golf Travel Agent

NAS Docker 部署的无头后端服务，供 Vercel 前端调用。

启动方式:
    uv run python -m travel_agent.server
    # 或
    uv run uvicorn travel_agent.server:app --host 0.0.0.0 --port 8080
"""

import asyncio
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from .graph import create_graph
from .tools.customer import authenticate_customer, get_customer_info

load_dotenv()

# ==============================================================================
# Configuration
# ==============================================================================

JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24
SESSION_TIMEOUT_MINUTES = 60
MAX_SESSIONS = 100

# ==============================================================================
# Pydantic Schemas
# ==============================================================================


class LoginRequest(BaseModel):
    """登录请求"""

    full_name: str  # 全名拼音 (Last, First)
    birthday: str  # YYYY-MM-DD
    trip_id: str  # 行程 Notion Page ID


class LoginResponse(BaseModel):
    """登录响应"""

    success: bool
    customer_id: str | None = None
    customer_info: dict | None = None
    session_id: str | None = None
    token: str | None = None
    error: str | None = None


class ChatRequest(BaseModel):
    """对话请求"""

    message: str
    include_thinking: bool = False


class ChatResponse(BaseModel):
    """对话响应"""

    response: str
    session_id: str


class HealthResponse(BaseModel):
    """健康检查响应"""

    status: str
    version: str
    active_sessions: int = 0


# ==============================================================================
# Session Management
# ==============================================================================


@dataclass
class Session:
    """用户会话"""

    session_id: str
    customer_id: str
    trip_id: str
    customer_info: dict
    thread_id: str
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    _graph: object = field(default=None, repr=False)
    _checkpointer: MemorySaver | None = field(default=None, repr=False)

    @property
    def graph(self):
        """延迟创建 graph"""
        if self._graph is None:
            self._checkpointer = MemorySaver()
            self._graph = create_graph(
                trip_id=self.trip_id,
                customer_id=self.customer_id,
                customer_info=self.customer_info,
                current_date=datetime.now().strftime("%Y年%m月%d日"),
                checkpointer=self._checkpointer,
            )
        return self._graph

    @property
    def config(self):
        """LangGraph 配置"""
        return {"configurable": {"thread_id": self.thread_id}}

    def touch(self):
        """更新最后活跃时间"""
        self.last_active = datetime.now()


class SessionManager:
    """会话管理器"""

    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        customer_id: str,
        trip_id: str,
        customer_info: dict,
    ) -> Session:
        """创建新会话"""
        async with self._lock:
            if len(self._sessions) >= MAX_SESSIONS:
                await self._evict_oldest()

            session = Session(
                session_id=str(uuid.uuid4()),
                customer_id=customer_id,
                trip_id=trip_id,
                customer_info=customer_info,
                thread_id=str(uuid.uuid4()),
            )
            self._sessions[session.session_id] = session
            return session

    def get(self, session_id: str) -> Session | None:
        """获取会话"""
        session = self._sessions.get(session_id)
        if session:
            elapsed = (datetime.now() - session.last_active).total_seconds()
            if elapsed > SESSION_TIMEOUT_MINUTES * 60:
                del self._sessions[session_id]
                return None
            session.touch()
        return session

    async def _evict_oldest(self):
        """移除最旧的会话"""
        if self._sessions:
            oldest = min(self._sessions.values(), key=lambda s: s.last_active)
            del self._sessions[oldest.session_id]

    @property
    def count(self) -> int:
        """活跃会话数"""
        return len(self._sessions)


session_manager = SessionManager()

# ==============================================================================
# JWT Authentication
# ==============================================================================

security = HTTPBearer()


def create_token(customer_id: str, session_id: str) -> str:
    """生成 JWT Token"""
    expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {
        "sub": customer_id,
        "session_id": session_id,
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """解码 JWT Token"""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


async def get_current_session(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Session:
    """FastAPI 依赖：获取当前会话"""
    payload = decode_token(credentials.credentials)
    session_id = payload.get("session_id")
    session = session_manager.get(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session not found or expired",
        )
    return session


# ==============================================================================
# FastAPI Application
# ==============================================================================

app = FastAPI(
    title="Golf Travel Agent API",
    version="0.1.0",
    description="高尔夫旅行智能助手 API - NAS Docker 部署版",
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
        version="0.1.0",
        active_sessions=session_manager.count,
    )


@app.post("/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """客户认证"""
    customer_info = authenticate_customer(
        full_name=request.full_name,
        birthday=request.birthday,
        trip_id=request.trip_id,
    )

    if not customer_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed: invalid credentials or no access to trip",
        )

    customer_id = customer_info.get("id")

    session = await session_manager.create(
        customer_id=customer_id,
        trip_id=request.trip_id,
        customer_info=customer_info,
    )

    token = create_token(customer_id, session.session_id)

    return LoginResponse(
        success=True,
        customer_id=customer_id,
        customer_info={
            "name": customer_info.get("name"),
            "handicap": customer_info.get("handicap"),
            "dietary_preferences": customer_info.get("dietary_preferences"),
        },
        session_id=session.session_id,
        token=token,
    )


def _extract_text_content(content) -> str:
    """提取文本内容（兼容多模态格式）"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content)


@app.post("/chat/invoke", response_model=ChatResponse)
async def chat_invoke(
    request: ChatRequest,
    session: Session = Depends(get_current_session),
):
    """单次对话（非流式）"""
    input_state = {"messages": [HumanMessage(content=request.message)]}
    result = session.graph.invoke(input_state, session.config)

    last_message = result["messages"][-1]
    return ChatResponse(
        response=_extract_text_content(last_message.content),
        session_id=session.session_id,
    )


@app.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    session: Session = Depends(get_current_session),
):
    """SSE 流式对话"""

    async def event_generator() -> AsyncGenerator[dict, None]:
        input_state = {"messages": [HumanMessage(content=request.message)]}

        try:
            async for event in session.graph.astream_events(
                input_state,
                session.config,
                version="v2",
            ):
                event_type = event.get("event")

                if event_type == "on_tool_start":
                    tool_name = event.get("name", "unknown")
                    yield {
                        "event": "tool_call",
                        "data": json.dumps(
                            {"tool": tool_name, "status": "started"}, ensure_ascii=False
                        ),
                    }

                elif event_type == "on_tool_end":
                    tool_name = event.get("name", "unknown")
                    output = event.get("data", {}).get("output", "")
                    summary = output[:200] + "..." if len(str(output)) > 200 else output
                    yield {
                        "event": "tool_result",
                        "data": json.dumps(
                            {"tool": tool_name, "summary": str(summary)},
                            ensure_ascii=False,
                        ),
                    }

                elif event_type == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content"):
                        content = _extract_text_content(chunk.content)
                        if content:
                            yield {
                                "event": "token",
                                "data": json.dumps(
                                    {"content": content}, ensure_ascii=False
                                ),
                            }

                elif event_type == "on_chain_end" and event.get("name") == "LangGraph":
                    output = event.get("data", {}).get("output", {})
                    messages = output.get("messages", [])
                    if messages:
                        final_content = _extract_text_content(messages[-1].content)
                        yield {
                            "event": "done",
                            "data": json.dumps(
                                {"full_response": final_content}, ensure_ascii=False
                            ),
                        }

        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}, ensure_ascii=False),
            }

    return EventSourceResponse(event_generator())


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
