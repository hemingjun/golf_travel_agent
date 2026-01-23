"""天气 API 封装 - 基于 Google Weather API

使用 Google Weather API 获取天气预报，支持 10 天预报。
地理编码使用 Google Geocoding API。
"""

import os
from datetime import datetime
from threading import Lock

import httpx
from cachetools import TTLCache

GOOGLE_WEATHER_URL = "https://weather.googleapis.com/v1"
GOOGLE_GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# 天气缓存：1小时 TTL，最多 64 条
WEATHER_CACHE: TTLCache = TTLCache(maxsize=64, ttl=3600)
WEATHER_LOCK = Lock()

# 地理编码缓存：24小时 TTL，最多 128 条
GEOCODING_CACHE: TTLCache = TTLCache(maxsize=128, ttl=86400)
GEOCODING_LOCK = Lock()


def _weather_cache_key(location: str, date: str) -> str:
    """生成天气缓存 key"""
    return f"{location.lower().strip()}:{date}"


def _get_google_api_key() -> str | None:
    """获取 Google Maps Platform API Key"""
    return os.getenv("GOOGLE_MAPS_API_KEY")


def _get_lat_lon(location: str) -> tuple[float, float] | None:
    """通过地名获取经纬度（使用 Google Geocoding API）

    Args:
        location: 地名（支持中文，如 "温哥华", "Los Cabos", "北京"）

    Returns:
        (lat, lon) 或 None
    """
    api_key = _get_google_api_key()
    if not api_key:
        return None

    # 检查缓存
    cache_key = location.lower().strip()
    with GEOCODING_LOCK:
        if cache_key in GEOCODING_CACHE:
            return GEOCODING_CACHE[cache_key]

    params = {"address": location, "key": api_key}

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(GOOGLE_GEOCODING_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") == "OK" and data.get("results"):
                loc = data["results"][0]["geometry"]["location"]
                coords = (loc["lat"], loc["lng"])

                # 写入缓存
                with GEOCODING_LOCK:
                    GEOCODING_CACHE[cache_key] = coords

                return coords
    except httpx.HTTPError:
        pass

    return None


def _get_weather_by_coords(lat: float, lon: float, target_date: str) -> dict | None:
    """通过经纬度获取天气预报（使用 Google Weather API）

    Args:
        lat: 纬度
        lon: 经度
        target_date: 目标日期 (YYYY-MM-DD)

    Returns:
        天气信息字典
    """
    api_key = _get_google_api_key()
    if not api_key:
        return None

    url = f"{GOOGLE_WEATHER_URL}/forecast/days:lookup"
    params = {
        "key": api_key,
        "location.latitude": lat,
        "location.longitude": lon,
        "days": 10,  # 请求 10 天预报
    }

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            # 解析目标日期的天气数据
            target = datetime.strptime(target_date, "%Y-%m-%d").date()

            for day in data.get("forecastDays", []):
                display_date = day.get("displayDate", {})
                day_date_str = f"{display_date.get('year')}-{display_date.get('month'):02d}-{display_date.get('day'):02d}"

                if day_date_str == target_date:
                    # 提取天气信息
                    daytime = day.get("daytimeForecast", {})
                    condition = daytime.get("condition", {})

                    max_temp = day.get("maxTemperature", {})
                    min_temp = day.get("minTemperature", {})

                    # 风速（取白天预报）
                    wind = daytime.get("wind", {})
                    wind_speed = wind.get("speed", {}).get("value", 0)

                    # 降水概率
                    precip = daytime.get("precipitation", {})
                    rain_prob = precip.get("probability", {}).get("value", 0)

                    return {
                        "date": target_date,
                        "weather": condition.get("description", "未知"),
                        "temp_max": round(max_temp.get("degrees", 0)),
                        "temp_min": round(min_temp.get("degrees", 0)),
                        "wind_speed": round(wind_speed, 1),
                        "rain_probability": round(rain_prob),
                    }

            return None

    except httpx.HTTPError as e:
        print(f"[Weather API] HTTP error: {e}")
        return None
    except Exception as e:
        print(f"[Weather API] Error: {e}")
        return None


def get_location_weather(location: str, target_date: str) -> dict | None:
    """便捷方法：通过地名直接获取天气（支持中文）

    Args:
        location: 地名（支持中文，如 "温哥华", "Los Cabos", "北京"）
        target_date: 目标日期 (YYYY-MM-DD)

    Returns:
        天气信息字典，或包含 error/message 的错误字典
    """
    # 1. 检查缓存
    cache_key = _weather_cache_key(location, target_date)
    with WEATHER_LOCK:
        if cache_key in WEATHER_CACHE:
            return WEATHER_CACHE[cache_key]

    # 2. API Key 检查
    if not _get_google_api_key():
        return {
            "error": "no_api_key",
            "message": "天气服务未配置（缺少 GOOGLE_MAPS_API_KEY）",
        }

    # 3. 日期格式校验
    try:
        datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        return {"error": "invalid_date", "message": f"日期格式错误: {target_date}"}

    # 4. 获取经纬度（Google Geocoding API）
    coords = _get_lat_lon(location)
    if not coords:
        return {"error": "location_not_found", "message": f"无法识别地名: {location}"}

    # 5. 获取天气（Google Weather API）
    weather = _get_weather_by_coords(coords[0], coords[1], target_date)
    if not weather:
        return {
            "error": "weather_not_found",
            "message": f"无法获取 {location} 在 {target_date} 的天气",
        }

    # 6. 写入缓存
    with WEATHER_LOCK:
        WEATHER_CACHE[cache_key] = weather

    return weather
