from app.config import settings
from app.services.rag_pipeline import retrieve_context, build_source_list


class KBTool:
    """Encapsulates the full RAG pipeline as an Agent-callable tool."""

    def __init__(self, embedding_service, vector_store, collection_name: str):
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.collection_name = collection_name

    def search(self, question: str, top_k: int = 4) -> tuple[str, list[dict]]:
        context, sources = retrieve_context(
            self.embedding_service, self.vector_store, self.collection_name,
            question, top_k, rerank_enabled=settings.rerank_enabled,
        )
        return context or "未找到相关文档。", sources


def get_tool_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "搜索知识库中的文档内容。当用户提问涉及已上传的 PDF 文档、"
                "需要查找具体资料信息时调用此工具。"
                "普通闲聊、问候等不需要调用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "要在知识库中检索的问题或关键词，建议使用完整句子以提高检索准确率",
                    }
                },
                "required": ["question"],
            },
        },
    }
