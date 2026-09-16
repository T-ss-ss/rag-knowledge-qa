import threading

from app.config import settings
from app.services.reranker_service import RerankerService

_reranker: RerankerService | None = None
_reranker_lock = threading.Lock()


def _get_reranker() -> RerankerService:
    """进程内单例：避免每个请求重复加载约 1.5GB 的 Reranker 模型。"""
    global _reranker
    if _reranker is None:
        with _reranker_lock:
            if _reranker is None:
                _reranker = RerankerService()
    return _reranker


def retrieve_context(
    embedding_service,
    vector_store,
    collection_name: str,
    question: str,
    top_k: int,
    rerank_enabled: bool = True,
    retrieval_k: int = 0,
) -> tuple[str, list[dict]]:
    """embed → retrieve → rerank → format. Returns (context_str, sources_list)."""
    query_embedding = embedding_service.embed_query(question)

    actual_k = retrieval_k if retrieval_k > 0 else top_k * settings.retrieval_multiplier
    if not rerank_enabled:
        actual_k = top_k

    documents, metadatas = vector_store.query(collection_name, query_embedding, actual_k)

    if rerank_enabled and settings.rerank_enabled and len(documents) > top_k:
        documents, metadatas = _get_reranker().rerank(
            question, documents, metadatas, top_k
        )

    context_parts = []
    for i, (doc, meta) in enumerate(zip(documents, metadatas)):
        filename = meta.get("filename", "unknown")
        page = meta.get("page", 0)
        # 页码不可知时（Web 来源、未记录页数的 DOCX）省略 Page 字段，
        # 避免把估算/编造的页码当事实喂给 LLM。
        locator = f"{filename}, Page {page}" if page > 0 else filename
        context_parts.append(
            f"[Source {i + 1}: {locator}]\n{doc}"
        )

    context = "\n\n".join(context_parts)
    sources = build_source_list(documents, metadatas)

    return context, sources


def build_source_list(documents: list[str], metadatas: list[dict]) -> list[dict]:
    return [
        {
            "document_id": meta.get("document_id", ""),
            "filename": meta.get("filename", "unknown"),
            # page = 0 表示页码不可知（Web 结果、未记录页数的文档），前端不展示
            "page": meta.get("page", 0),
            "chunk_index": meta.get("chunk_index", -1),
            "content": doc[:500],
            "relevance_score": meta.get("relevance_score", 0.0),
            # relevance_score 的量纲随检索路径变化：
            # cosine = 1 - 余弦距离（-1~1） / rerank = BGE sigmoid 归一化（0~1） / web = Tavily score
            "score_type": meta.get("score_type", "cosine"),
        }
        for doc, meta in zip(documents, metadatas)
    ]


def extract_summary(text: str, max_len: int = 100) -> str:
    for sep in ["。", "\n\n", ". "]:
        parts = text.split(sep, 1)
        if len(parts) > 1:
            return parts[0].strip()[:max_len]
    return text[:max_len]


def deduplicate_sources(sources: list[dict]) -> list[dict]:
    """按 (document_id, chunk_index) 去重。

    不能用 (document_id, page) 做键：页码不可知时同一文档的多个召回块页码
    同为 0，会被错误地合并成一条，导致来源数量凭空减少。
    Web 结果没有 chunk_index（恒为 -1），靠各自的 url 区分。
    """
    seen = set()
    unique = []
    for s in sources:
        key = (s.get("document_id", ""), s.get("chunk_index", -1))
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique
