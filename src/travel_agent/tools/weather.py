"""天气预报工具"""

from datetime import datetime

from langchain_core.tools import tool

from ..utils.debug import debug_print
from ._weather_api import get_location_weather


def create_weather_tool():
    """创建天气预报查询工具"""

    @tool
    def query_weather(location: str, date: str = "") -> str:
        """查询天气预报

        支持并行调用。如果需要查询多天或多个城市天气，请一次性输出多个 query_weather 调用。

        Args:
            location: 地点名称（支持中文和英文，如 "Los Cabos", "北京"）
            date: 目标日期，格式 YYYY-MM-DD（默认为今天）

        返回：天气描述、温度范围、降水概率、风速

        注意：天气预报仅支持未来 5 天
        """
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        try:
            clean_date = date.replace("年", "-").replace("月", "-").replace("日", "")
            parsed = datetime.strptime(clean_date.split("T")[0].strip(), "%Y-%m-%d")
            date = parsed.strftime("%Y-%m-%d")
        except ValueError:
            pass

        debug_print(f"[Weather] 查询天气: {location} @ {date}")

        weather = get_location_weather(location, date)

        if not weather:
            return f"无法获取 {location} 在 {date} 的天气信息"

        if "error" in weather:
            return f"天气查询失败: {weather.get('message', weather.get('error'))}"

        output = f"【{location} 天气预报】({date})\n"
        output += f"天气: {weather.get('weather', '未知')}\n"
        output += f"温度: {weather.get('temp_min', '?')}°C ~ {weather.get('temp_max', '?')}°C\n"
        output += f"降水概率: {weather.get('rain_probability', '?')}%\n"
        if weather.get("wind_speed"):
            output += f"风速: {weather.get('wind_speed')} m/s\n"

        return output

    return query_weather
