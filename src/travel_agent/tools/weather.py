"""天气查询工具 - 基于 OpenWeatherMap API"""

import os
from datetime import datetime, timedelta

import httpx

BASE_URL = "https://api.openweathermap.org"


def _get_api_key() -> str | None:
    """动态获取 API Key"""
    return os.getenv("OPENWEATHER_API_KEY")


def _get_lat_lon(city_name: str) -> tuple[float, float] | None:
    """通过城市名获取经纬度（支持中文）

    使用 OpenWeatherMap Geocoding API，原生支持中文城市名。

    Args:
        city_name: 城市名（如 "温哥华", "Vancouver", "北京"）

    Returns:
        (lat, lon) 或 None
    """
    api_key = _get_api_key()
    if not api_key:
        return None

    url = f"{BASE_URL}/geo/1.0/direct"
    params = {"q": city_name, "limit": 1, "appid": api_key}

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            if data:
                return (data[0]["lat"], data[0]["lon"])
    except httpx.HTTPError:
        pass

    return None


def _get_weather_by_coords(lat: float, lon: float, target_date: str) -> dict | None:
    """通过经纬度获取天气预报

    Args:
        lat: 纬度
        lon: 经度
        target_date: 目标日期 (YYYY-MM-DD)

    Returns:
        天气信息字典
    """
    api_key = _get_api_key()
    if not api_key:
        return None

    url = f"{BASE_URL}/data/2.5/forecast"
    params = {
        "lat": lat,
        "lon": lon,
        "appid": api_key,
        "units": "metric",
        "lang": "zh_cn",
    }

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            # 解析目标日期的天气数据
            target = datetime.strptime(target_date, "%Y-%m-%d").date()
            day_forecasts = []

            for item in data.get("list", []):
                dt = datetime.fromtimestamp(item["dt"]).date()
                if dt == target:
                    day_forecasts.append(item)

            if not day_forecasts:
                return None

            # 聚合当天数据
            temps = [f["main"]["temp"] for f in day_forecasts]
            winds = [f["wind"]["speed"] for f in day_forecasts]
            weather_desc = day_forecasts[len(day_forecasts) // 2]["weather"][0][
                "description"
            ]

            # 计算降水概率
            rain_probs = [f.get("pop", 0) * 100 for f in day_forecasts]
            max_rain_prob = max(rain_probs) if rain_probs else 0

            return {
                "date": target_date,
                "weather": weather_desc,
                "temp_max": round(max(temps)),
                "temp_min": round(min(temps)),
                "wind_speed": round(sum(winds) / len(winds), 1),
                "rain_probability": round(max_rain_prob),
            }
    except httpx.HTTPError:
        return None


def get_location_weather(location: str, target_date: str) -> dict | None:
    """便捷方法：通过地名直接获取天气（支持中文）

    Args:
        location: 地名（支持中文，如 "温哥华", "北京"）
        target_date: 目标日期 (YYYY-MM-DD)

    Returns:
        天气信息字典，或包含 error/message 的错误字典
    """
    # 1. API Key 检查
    if not _get_api_key():
        return {"error": "no_api_key", "message": "天气服务未配置（缺少 OPENWEATHER_API_KEY）"}

    # 2. 日期范围校验
    today = datetime.now().date()
    try:
        target = datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        return {"error": "invalid_date", "message": f"日期格式错误: {target_date}"}

    if target < today:
        return {"error": "past_date", "message": f"{target_date} 是过去的日期，无法获取历史天气"}

    max_date = today + timedelta(days=5)
    if target > max_date:
        return {"error": "out_of_range", "message": f"{target_date} 超出预报范围（最多未来5天）"}

    # 3. 获取经纬度（Geocoding API 原生支持中文）
    coords = _get_lat_lon(location)
    if not coords:
        return {"error": "location_not_found", "message": f"无法识别地名: {location}"}

    # 4. 获取天气
    weather = _get_weather_by_coords(coords[0], coords[1], target_date)
    if not weather:
        return {"error": "weather_not_found", "message": f"无法获取 {location} 在 {target_date} 的天气"}

    return weather
