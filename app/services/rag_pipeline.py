import threading

from app.config import settings
from app.services import bm25_retriever
from app.services.reranker_service import RerankerService

_reranker: RerankerService | None = None
_reranker_lock = threading.Lock()


def _get_reranker() -> RerankerService:
    """进程内单例：避免每个请求重复加载约 2.1GB 的 Reranker 模型。"""
    global _reranker
    if _reranker is None:
        with _reranker_lock:
            if _reranker is None:
                _reranker = RerankerService()
    return _reranker


def hybrid_search(
    vector_store,
    collection_name: str,
    question: str,
    query_embedding: list[float],
    candidate_k: int,
) -> tuple[list[str], list[dict]]:
    """稠密 + 稀疏双路召回，用 RRF 融合后返回 candidate_k 条。

    RRF (Reciprocal Rank Fusion)：只用排名、不用分数：
        score(d) = Σ_i 1 / (rrf_k + rank_i(d))
    这样不必把余弦相似度（-1~1）与 BM25 分数（无上界、因语料而异）硬凑到一起，
    也不需要对两路分数做归一化——这是它比"加权求和"更稳的原因。

    任一路为空时自动退化为另一路，不会让检索整体失败。
    """
    dense_ids, dense_docs, dense_metas = vector_store.query_with_ids(
        collection_name, query_embedding, candidate_k
    )

    index = bm25_retriever.get_index(vector_store, collection_name)
    if index is None:
        return dense_docs, dense_metas

    sparse_hits = index.search(question, candidate_k)
    if not sparse_hits:
        # 查询词全部不在 BM25 词表内（纯符号、未见过的英文缩写等）
        return dense_docs, dense_metas

    hits_dense = set(dense_ids)
    hits_sparse = {cid for cid, _, _ in sparse_hits}

    scores: dict[str, float] = {}
    payload: dict[str, tuple[str, dict]] = {}
    cosine: dict[str, float] = {}

    for rank, (cid, doc, meta) in enumerate(zip(dense_ids, dense_docs, dense_metas)):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (settings.rrf_k + rank + 1)
        payload[cid] = (doc, meta)
        cosine[cid] = meta.get("relevance_score", 0.0)

    for cid, _bm25, rank in sparse_hits:
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (settings.rrf_k + rank + 1)
        if cid not in payload:
            got = index.get(cid)
            if got is None:
                continue
            payload[cid] = got

    ranked = sorted(scores.items(), key=lambda t: t[1], reverse=True)[:candidate_k]

    documents: list[str] = []
    metadatas: list[dict] = []
    for cid, fused in ranked:
        doc, meta = payload[cid]
        meta = dict(meta)
        # 保留稠密分数便于排查；对外分数改用融合分，量纲标记为 rrf
        if cid in cosine:
            meta["cosine_score"] = cosine[cid]
        meta["rrf_score"] = round(fused, 6)
        meta["relevance_score"] = round(fused, 6)
        meta["score_type"] = "rrf"
        meta["retrieval"] = (
            "both" if cid in hits_dense and cid in hits_sparse
            else ("dense" if cid in hits_dense else "sparse")
        )
        documents.append(doc)
        metadatas.append(meta)

    return documents, metadatas


def retrieve_context(
    embedding_service,
    vector_store,
    collection_name: str,
    question: str,
    top_k: int,
    rerank_enabled: bool = True,
    retrieval_k: int = 0,
    hybrid_enabled: bool | None = None,
) -> tuple[str, list[dict]]:
    """embed → retrieve → rerank → format. Returns (context_str, sources_list).

    hybrid_enabled=None 时取全局配置；显式传值用于 A/B 对比（见 eval/）。
    """
    query_embedding = embedding_service.embed_query(question)

    use_hybrid = settings.hybrid_enabled if hybrid_enabled is None else hybrid_enabled

    # 精排要两个开关同时为真：请求级 rerank（调用方可单独关掉）与全局
    # RERANK_ENABLED。**必须用同一个 use_rerank 决定候选池大小**，否则会出现
    # "扩大了候选池却没有机制筛掉多出来的部分"——那些块会被原样塞进上下文
    # （实测一次喂给 LLM 12 条而非 4 条，token 直接 ×3）。
    use_rerank = rerank_enabled and settings.rerank_enabled
    actual_k = retrieval_k if retrieval_k > 0 else (
        top_k * settings.retrieval_multiplier if use_rerank else top_k
    )

    if use_hybrid:
        documents, metadatas = hybrid_search(
            vector_store, collection_name, question, query_embedding, actual_k
        )
    else:
        documents, metadatas = vector_store.query(
            collection_name, query_embedding, actual_k
        )

    if use_rerank and len(documents) > top_k:
        documents, metadatas = _get_reranker().rerank(
            question, documents, metadatas, top_k
        )
    else:
        # 无论走哪条路径，喂给 LLM 的都必须是 top_k 条
        documents, metadatas = documents[:top_k], metadatas[:top_k]

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
