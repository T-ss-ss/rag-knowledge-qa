import logging

import requests

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"


class WebSearchTool:
    """Tavily API wrapper — callable by Agent as search_web tool."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, max_results: int = 5) -> tuple[str, list[dict]]:
        try:
            resp = requests.post(
                TAVILY_URL,
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("Tavily search failed: %s", e)
            return f"联网搜索失败: {e}", []

        results = data.get("results", [])
        if not results:
            return "未找到相关网络信息。", []

        context_parts: list[str] = []
        for i, r in enumerate(results):
            title = r.get("title", "无标题")
            url = r.get("url", "")
            content = r.get("content", "")
            context_parts.append(
                f"[Web Source {i + 1}: {title}]\n{url}\n{content}"
            )

        context = "\n\n".join(context_parts)

        sources = []
        for r in results:
            sources.append({
                "document_id": r.get("url", ""),
                "filename": r.get("title", "无标题"),
                # Web 结果没有页码概念，0 = 不适用；前端据此不展示页码
                "page": 0,
                "content": (r.get("content") or "")[:500],
                "relevance_score": round(r.get("score", 0.5), 4),
                "score_type": "web",
            })

        return context, sources


def get_web_search_tool_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "搜索互联网获取最新信息、新闻、实时数据。"
                "当知识库中找不到相关内容，或用户的问题明显需要最新/实时信息"
                "（如天气、新闻、股价、最新动态等）时调用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "要在互联网上搜索的关键词或问题，建议使用简洁的关键词组合",
                    }
                },
                "required": ["query"],
            },
        },
    }
