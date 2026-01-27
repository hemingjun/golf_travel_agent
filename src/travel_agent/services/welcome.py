"""欢迎消息生成服务

封装 /welcome 端点的业务逻辑，包括：
- 行程数据获取
- 天气查询
- LLM 欢迎语生成
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
    """获取 Welcome 专用的 LLM 实例"""
    global _welcome_llm
    if _welcome_llm is None:
        from ..utils.llm_wrapper import create_self_healing_llm
        _welcome_llm = create_self_healing_llm(
            model="gemini-3-flash-preview",
            temperature=0.3,
            request_timeout=30,
            max_retries=2,
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
    async def generate_greeting(
        trip_id: str,
        customer_id: str,
        date: str,
    ) -> dict:
        """生成欢迎消息

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

        # 检查缓存
        cache_key = cache_manager.get_welcome_cache_key(trip_id, customer_id, date)
        cached = cache_manager.get_welcome(cache_key)
        if cached:
            print(f"[Welcome] Cache hit: {cache_key}")
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

        # 第一阶段并行：客户信息 + 行程日期 + 位置
        phase1_tasks = [
            WelcomeService.get_trip_dates_async(trip_id),
            WelcomeService.get_trip_location_async(trip_id),
        ]
        if not is_admin:
            phase1_tasks.append(WelcomeService.get_customer_info_async(customer_id))

        phase1_results = await asyncio.gather(*phase1_tasks, return_exceptions=True)

        trip_dates = phase1_results[0] if not isinstance(phase1_results[0], Exception) else (None, None)
        trip_start, trip_end_date = trip_dates

        location = phase1_results[1] if not isinstance(phase1_results[1], Exception) else "Unknown"
        if isinstance(location, Exception):
            location = "Unknown"

        customer_name = "管理员"
        customer_info = None
        if not is_admin and len(phase1_results) > 2:
            customer_info = phase1_results[2] if not isinstance(phase1_results[2], Exception) else None
            if customer_info:
                customer_name = customer_info.get("name", "客户")

        phase1_time = time.time() - start_time
        print(f"[Welcome] Phase 1: {phase1_time:.2f}s")

        # 缓存会话上下文
        cache_manager.set_session(
            thread_id=thread_id,
            trip_id=trip_id,
            customer_id=customer_id,
            date=current_date,
            expires_after=trip_end_date,
        )

        config = {
            "configurable": {
                "thread_id": thread_id,
                "trip_id": trip_id,
                "customer_id": customer_id,
                "customer_info": customer_info,
                "current_date": current_date,
            }
        }

        # 确定天气查询日期
        if trip_start and today_iso < trip_start:
            days_until_trip = (datetime.strptime(trip_start, "%Y-%m-%d") -
                              datetime.strptime(today_iso, "%Y-%m-%d")).days
            weather_date = trip_start if days_until_trip <= 10 else today_iso
        else:
            weather_date = today_iso

        # 第二阶段并行：行程数据 + 天气数据
        phase2_start = time.time()
        itinerary_task = WelcomeService.get_itinerary_data_async(trip_id, config)
        weather_task = WelcomeService.get_weather_data_async(location, weather_date)

        itinerary_data, weather_data = await asyncio.gather(
            itinerary_task, weather_task, return_exceptions=True
        )

        if isinstance(itinerary_data, Exception):
            itinerary_data = f"行程数据获取失败: {itinerary_data}"
        if isinstance(weather_data, Exception):
            weather_data = f"天气数据获取失败: {weather_data}"

        phase2_time = time.time() - phase2_start
        print(f"[Welcome] Phase 2: {phase2_time:.2f}s")

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
        phase3_start = time.time()
        try:
            llm = _get_welcome_llm()
            response = await llm.ainvoke([HumanMessage(content=greeting_prompt)])
            greeting = _extract_text_content(response.content)
        except Exception as e:
            return {
                "success": False,
                "error": f"生成欢迎消息失败: {e}",
            }

        phase3_time = time.time() - phase3_start
        total_time = time.time() - start_time
        print(f"[Welcome] Phase 3: {phase3_time:.2f}s, Total: {total_time:.2f}s")

        if not greeting or not greeting.strip():
            return {
                "success": False,
                "error": "生成欢迎消息失败：LLM 返回空内容",
            }

        # 写入缓存
        cache_manager.set_welcome(cache_key, greeting, customer_name, thread_id)

        return {
            "success": True,
            "customer_name": customer_name,
            "greeting": greeting,
            "thread_id": thread_id,
        }
