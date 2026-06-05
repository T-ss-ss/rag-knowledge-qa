from app.config import settings
from app.services.reranker_service import RerankerService


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
        reranker = RerankerService()
        documents, metadatas = reranker.rerank(question, documents, metadatas, top_k)

    context_parts = []
    for i, (doc, meta) in enumerate(zip(documents, metadatas)):
        filename = meta.get("filename", "unknown")
        page = meta.get("page", 0)
        context_parts.append(
            f"[Source {i + 1}: {filename}, Page {page}]\n{doc}"
        )

    context = "\n\n".join(context_parts)
    sources = build_source_list(documents, metadatas)

    return context, sources


def build_source_list(documents: list[str], metadatas: list[dict]) -> list[dict]:
    return [
        {
            "document_id": meta.get("document_id", ""),
            "filename": meta.get("filename", "unknown"),
            "page": meta.get("page", 0),
            "content": doc[:500],
            "relevance_score": meta.get("relevance_score", 0.0),
        }
        for doc, meta in zip(documents, metadatas)
    ]


def extract_summary(text: str, max_len: int = 100) -> str:
    for sep in ["。", "\n\n", ". "]:
        parts = text.split(sep, 1)
        if len(parts) > 1:
            return parts[0].strip()
    return text[:max_len]


def deduplicate_sources(sources: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for s in sources:
        key = (s.get("document_id", ""), s.get("page", 0))
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique
