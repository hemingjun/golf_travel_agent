"""API Pydantic 模型定义"""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """健康检查响应"""

    status: str
    version: str


class LoginRequest(BaseModel):
    """客户登录请求"""

    full_name: str  # 全名拼音 (Last, First)，输入 "admin" 可跳过生日验证
    birthday: str | None = None  # 生日 YYYY-MM-DD，admin 登录时可省略


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


class TripInfo(BaseModel):
    """行程信息"""

    trip_id: str
    trip_name: str
    start_date: str | None = None
    end_date: str | None = None
    status: str  # 未开始/进行中/已结束
    customer_count: int = 0


class UpcomingTripsResponse(BaseModel):
    """行程列表响应"""

    success: bool
    trips: list[TripInfo] = []
    error: str | None = None


class CustomerTripInfo(BaseModel):
    """客户行程信息（用于 /customers/{id}/trips）"""

    id: str  # 行程 Page ID
    name: str  # 行程名称
    destination: str = ""  # 目的地
    start_date: str | None = None  # YYYY-MM-DD
    end_date: str | None = None  # YYYY-MM-DD
    status: str  # upcoming/ongoing/completed


class CustomerTripsResponse(BaseModel):
    """客户行程列表响应"""

    success: bool
    trips: list[CustomerTripInfo] = []
    error: str | None = None
