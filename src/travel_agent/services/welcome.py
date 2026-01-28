"""欢迎消息生成服务

封装 /welcome 端点的业务逻辑，包括：
- 行程数据获取
- 天气查询
- LLM 欢迎语生成

优化特性：
- 共享缓存层：行程+日期维度的数据缓存，多客户共享
- 分层缓存：完整 Welcome 缓存 > 共享数据缓存 > API 调用
- 预期性能：缓存命中 <100ms，共享命中 1-2s，首次 2-4s
"""

import asyncio
import time
import uuid
from datetime import datetime

from langchain_core.messages import HumanMessage

from ..cache import cache_manager
from ..tools.customer import get_customer_info
from ..tools.itinerary import query_itinerary
from ..tools._weather_api import get_location_weather_async
from ..utils.notion import DATABASES, get_client
from ..tools._utils import _extract_text


# LLM 单例
_welcome_llm = None


def _get_welcome_llm():
    """获取 Welcome 专用的 LLM 实例

    优化配置：
    - 使用更快的模型：gemini-2.0-flash
    - 缩短超时时间：30s → 12s（欢迎语不需要太长）
    - 减少重试次数：2 → 1（快速失败，避免用户等待）
    - 禁用 fallback：Welcome 场景简单，不需要复杂的降级逻辑
    - 限制输出长度：512 tokens（欢迎语简洁为主）
    """
    global _welcome_llm
    if _welcome_llm is None:
        from ..utils.llm_wrapper import create_self_healing_llm
        _welcome_llm = create_self_healing_llm(
            model="gemini-2.0-flash",  # 使用更快的稳定版本
            fallback_model=None,       # 禁用 fallback，减少延迟
            temperature=0.3,
            request_timeout=12,        # 缩短超时
            max_retries=1,             # 减少重试
            max_output_tokens=512,     # 限制输出长度
        )
    return _welcome_llm


def _format_date_cn(date_iso: str) -> str:
    """将 ISO 日期转换为中文格式"""
    dt = datetime.strptime(date_iso, "%Y-%m-%d")
    return dt.strftime("%Y年%m月%d日")


def _extract_text_content(content) -> str:
    """从 LLM 响应中提取纯文本"""
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


class WelcomeService:
    """欢迎消息服务"""

    @staticmethod
    def get_trip_location(trip_id: str) -> str:
        """从行程中提取位置信息（用于天气查询）"""
        client = get_client()

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
                    return address
        except Exception as e:
            print(f"[Location] 查询球场失败: {e}")

        # 3. 降级：从行程名称提取目的地
        destination = WelcomeService.get_trip_destination(trip_id)
        if destination:
            return destination

        return "Unknown"

    @staticmethod
    def get_trip_destination(trip_id: str) -> str:
        """从行程中提取目的地（简化版）"""
        client = get_client()

        try:
            trip_page = client.get_page(trip_id)
            props = trip_page.get("properties", {})
            trip_name = props.get("Name", "") or ""

            if trip_name:
                parts = trip_name.split()
                if parts and parts[0][0].isdigit():
                    destination_parts = parts[1:]
                else:
                    destination_parts = []
                    for part in parts:
                        if part[0].isdigit():
                            break
                        destination_parts.append(part)
                if destination_parts:
                    return " ".join(destination_parts)
        except Exception as e:
            print(f"[Destination] 从行程名称提取失败: {e}")

        return ""

    @staticmethod
    def get_trip_dates(trip_id: str) -> tuple[str | None, str | None]:
        """获取行程开始/结束日期"""
        client = get_client()
        start_date = None
        end_date = None

        try:
            trip_info = client.get_page(trip_id)
            trip_date_str = trip_info.get("properties", {}).get("项目日期", "")

            if "→" in str(trip_date_str):
                parts = str(trip_date_str).split("→")
                start_date = parts[0].strip()
                end_date = parts[1].strip()
            elif trip_date_str:
                start_date = str(trip_date_str).strip()
                end_date = start_date
        except Exception as e:
            print(f"[TripDate] 获取行程日期失败: {e}")

        return start_date, end_date

    @staticmethod
    async def get_customer_info_async(customer_id: str) -> dict | None:
        """异步获取客户信息"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, get_customer_info, customer_id)

    @staticmethod
    async def get_itinerary_data_async(trip_id: str, config: dict) -> str:
        """异步获取行程数据"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, query_itinerary.invoke, {}, config)

    @staticmethod
    async def get_trip_location_async(trip_id: str) -> str:
        """异步获取行程位置"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, WelcomeService.get_trip_location, trip_id)

    @staticmethod
    async def get_trip_dates_async(trip_id: str) -> tuple[str | None, str | None]:
        """异步获取行程日期"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, WelcomeService.get_trip_dates, trip_id)

    @staticmethod
    async def get_weather_data_async(location: str, weather_date: str) -> str:
        """异步获取天气数据"""
        weather = await get_location_weather_async(location, weather_date)

        if not weather:
            return f"无法获取 {location} 在 {weather_date} 的天气信息"

        if "error" in weather:
            return f"天气查询失败: {weather.get('message', weather.get('error'))}"

        output = f"【{location} 天气预报】({weather_date})\n"
        output += f"天气: {weather.get('weather', '未知')}\n"
        output += f"温度: {weather.get('temp_min', '?')}°C ~ {weather.get('temp_max', '?')}°C\n"
        output += f"降水概率: {weather.get('rain_probability', '?')}%\n"
        if weather.get("wind_speed"):
            output += f"风速: {weather.get('wind_speed')} m/s\n"

        return output

    @staticmethod
    async def _get_shared_data(trip_id: str, date: str) -> dict:
        """获取共享数据（多客户共享）

        共享数据包含行程信息和天气数据，对同一行程的所有客户都相同。
        优先从共享缓存获取，缓存未命中时并行获取。

        Returns:
            {
                "trip_dates": (start, end),
                "location": str,
                "itinerary": str,
                "weather": str,
                "weather_date": str,
            }
        """
        shared_key = cache_manager.get_shared_data_key(trip_id, date)

        # 1. 检查共享缓存
        cached = cache_manager.get_shared_data(shared_key)
        if cached:
            print(f"[Welcome] Shared cache HIT: {shared_key[:40]}...")
            return cached

        print(f"[Welcome] Shared cache MISS: {shared_key[:40]}...")

        # 2. 并行获取共享数据
        trip_dates_task = WelcomeService.get_trip_dates_async(trip_id)
        location_task = WelcomeService.get_trip_location_async(trip_id)

        # 先获取日期和位置（用于确定天气查询参数）
        trip_dates, location = await asyncio.gather(
            trip_dates_task, location_task, return_exceptions=True
        )

        if isinstance(trip_dates, Exception):
            trip_dates = (None, None)
        if isinstance(location, Exception):
            location = "Unknown"

        trip_start, trip_end = trip_dates

        # 确定天气查询日期
        if trip_start and date < trip_start:
            days_until_trip = (datetime.strptime(trip_start, "%Y-%m-%d") -
                              datetime.strptime(date, "%Y-%m-%d")).days
            weather_date = trip_start if days_until_trip <= 10 else date
        else:
            weather_date = date

        # 构建行程查询 config（不包含 customer_info，共享数据不需要）
        config = {
            "configurable": {
                "thread_id": f"shared-{trip_id}",
                "trip_id": trip_id,
                "current_date": _format_date_cn(date),
            }
        }

        # 并行获取行程和天气
        itinerary_task = WelcomeService.get_itinerary_data_async(trip_id, config)
        weather_task = WelcomeService.get_weather_data_async(location, weather_date)

        itinerary_data, weather_data = await asyncio.gather(
            itinerary_task, weather_task, return_exceptions=True
        )

        if isinstance(itinerary_data, Exception):
            itinerary_data = f"行程数据获取失败: {itinerary_data}"
        if isinstance(weather_data, Exception):
            weather_data = f"天气数据获取失败: {weather_data}"

        # 3. 构建共享数据
        shared_data = {
            "trip_dates": trip_dates,
            "location": location,
            "itinerary": itinerary_data,
            "weather": weather_data,
            "weather_date": weather_date,
        }

        # 4. 缓存共享数据（1 小时）
        cache_manager.set_shared_data(shared_key, shared_data)

        return shared_data

    @staticmethod
    async def _get_customer_name_fast(customer_id: str) -> str:
        """快速获取客户名称

        这是个性化数据，每个客户独立。
        由于 Notion 页面有缓存，通常 <100ms。
        """
        if customer_id.lower() == "admin":
            return "管理员"

        try:
            customer_info = await WelcomeService.get_customer_info_async(customer_id)
            if customer_info:
                return customer_info.get("name", "客户")
        except Exception as e:
            print(f"[Welcome] Get customer name failed: {e}")

        return "客户"

    @staticmethod
    async def generate_greeting(
        trip_id: str,
        customer_id: str,
        date: str,
    ) -> dict:
        """生成欢迎消息

        优化后的三层缓存策略：
        1. 完整 Welcome 缓存：<100ms（客户维度）
        2. 共享数据缓存：1-2s（行程+日期维度，只需 LLM 调用）
        3. 无缓存：2-4s（完整流程）

        Returns:
            {
                "success": bool,
                "customer_name": str,
                "greeting": str,
                "thread_id": str,
                "error": str | None
            }
        """
        start_time = time.time()

        # 验证日期格式
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return {
                "success": False,
                "error": f"日期格式错误: {date}，应为 YYYY-MM-DD",
            }

        # =====================================================================
        # 第 1 层：完整 Welcome 缓存
        # =====================================================================
        cache_key = cache_manager.get_welcome_cache_key(trip_id, customer_id, date)
        cached = cache_manager.get_welcome(cache_key)
        if cached:
            print(f"[Welcome] Full cache HIT: {cache_key[:40]}... ({time.time() - start_time:.3f}s)")
            return {
                "success": True,
                "customer_name": cached["customer_name"],
                "greeting": cached["greeting"],
                "thread_id": cached["thread_id"],
            }

        today_iso = date
        current_date = _format_date_cn(date)
        thread_id = str(uuid.uuid4())
        is_admin = customer_id.lower() == "admin"

        # =====================================================================
        # 第 2 层：共享数据缓存 + 客户名称
        # =====================================================================
        phase1_start = time.time()

        # 并行获取：共享数据 + 客户名称
        shared_task = WelcomeService._get_shared_data(trip_id, date)
        name_task = WelcomeService._get_customer_name_fast(customer_id)

        shared_data, customer_name = await asyncio.gather(shared_task, name_task)

        # 解析共享数据
        trip_dates = shared_data["trip_dates"]
        trip_start, trip_end_date = trip_dates
        location = shared_data["location"]
        itinerary_data = shared_data["itinerary"]
        weather_data = shared_data["weather"]
        weather_date = shared_data["weather_date"]

        phase1_time = time.time() - phase1_start
        print(f"[Welcome] Phase 1 (shared+name): {phase1_time:.2f}s")

        # 缓存会话上下文
        cache_manager.set_session(
            thread_id=thread_id,
            trip_id=trip_id,
            customer_id=customer_id,
            date=current_date,
            expires_after=trip_end_date,
        )

        # =====================================================================
        # 第 3 层：LLM 生成
        # =====================================================================
        phase2_start = time.time()

        # 构建 greeting_prompt
        trip_start_cn = _format_date_cn(trip_start) if trip_start else "未知"
        weather_date_cn = _format_date_cn(weather_date)
        weather_type = "行程首日预报" if weather_date != today_iso else "当天天气"
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
4. 服务介绍要具体说明助手能做什么

注意：直接生成回复，不需要调用工具。"""

        # 调用 LLM
        try:
            llm = _get_welcome_llm()
            response = await llm.ainvoke([HumanMessage(content=greeting_prompt)])
            greeting = _extract_text_content(response.content)
        except Exception as e:
            return {
                "success": False,
                "error": f"生成欢迎消息失败: {e}",
            }

        phase2_time = time.time() - phase2_start
        total_time = time.time() - start_time
        print(f"[Welcome] Phase 2 (LLM): {phase2_time:.2f}s, Total: {total_time:.2f}s")

        if not greeting or not greeting.strip():
            return {
                "success": False,
                "error": "生成欢迎消息失败：LLM 返回空内容",
            }

        # 写入完整 Welcome 缓存
        cache_manager.set_welcome(cache_key, greeting, customer_name, thread_id)

        return {
            "success": True,
            "customer_name": customer_name,
            "greeting": greeting,
            "thread_id": thread_id,
        }
