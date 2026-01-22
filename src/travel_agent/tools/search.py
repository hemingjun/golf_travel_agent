"""网络搜索工具 - 使用 Gemini 原生 Google Search"""

import os

from langchain_core.tools import tool

from ..utils.debug import debug_print


@tool
def search_web(query: str) -> str:
    """搜索互联网公开信息（使用 Google Search）

    支持并行调用。如果需要搜索多个主题，请一次性输出多个 search_web 调用。

    Args:
        query: 搜索查询词（建议使用英文以获得更好结果）

    适用场景：
    - 酒店/球场评价和口碑
    - 球场攻略和打球技巧
    - 当地旅游信息和餐厅推荐
    - 汇率查询

    使用建议：
    1. 先调用 query_hotel_bookings 或 query_golf_bookings 获取具体名称
    2. 用具体名称搜索，如 "Cabo del Sol golf course reviews"
    3. 添加地点限定词避免歧义，如 "Sheraton Los Cabos reviews"

    禁止：
    - 搜索泛泛的词如"酒店评价"（必须有具体酒店名）
    - 搜索行程预订信息（那些在内部数据库中）

    返回：
    - 搜索结果摘要，包含来源链接
    """
    try:
        from google import genai
        from google.genai import types

        debug_print(f"[Search] 搜索: {query}")

        # 使用 GOOGLE_API_KEY 环境变量
        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=query,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            ),
        )

        result = response.text or ""

        # 提取 grounding metadata（来源引用）
        if response.candidates and response.candidates[0].grounding_metadata:
            metadata = response.candidates[0].grounding_metadata

            # 添加搜索来源
            if metadata.grounding_chunks:
                sources = []
                for chunk in metadata.grounding_chunks[:3]:
                    if hasattr(chunk, "web") and chunk.web:
                        sources.append(f"- {chunk.web.title}: {chunk.web.uri}")
                if sources:
                    result += "\n\n来源:\n" + "\n".join(sources)

        return f"【搜索结果】{query}\n\n{result}"

    except Exception as e:
        debug_print(f"[Search] 搜索失败: {e}")
        return f"搜索失败: {str(e)[:100]}"
