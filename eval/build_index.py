"""构建评测用的检索索引（与业务知识库完全隔离）。

为什么不用业务知识库当评测语料
--------------------------------
线上 `kb_default` 只有 12 个 chunk，而 reranker 的候选池默认是
`top_k × retrieval_multiplier = 4 × 3 = 12`——恰好等于全库。此时"扩大候选池"
与"不扩大候选池"会退化成同一个配置，测不出精排的贡献。所以要有一个规模
足够的语料。

评测语料
--------
项目根目录下的全部 Markdown 文档，约 17 万字符 → 173 个 chunk。
选它的理由：真实、可复现、无隐私问题，且内容之间存在真实的知识库常见的
语义交叉与近似重复（README / ARCHITECTURE / PROJECT_PORTFOLIO 都在讲架构）。

用法
----
    python eval/build_index.py              # 语料未变则复用嵌入缓存
    python eval/build_index.py --no-cache   # 忽略缓存，强制重新调用 API
"""

import argparse
import json
import sys
import time

import _common  # noqa: F401  必须最先导入：注入 CHROMA_PERSIST_DIR
from _common import CACHE_DIR, COLLECTION, EVAL_DIR, PROJECT_ROOT, embed_cached, sha1

from app.config import settings  # noqa: E402
from app.services.chunking_service import ChunkingService  # noqa: E402

MANIFEST = EVAL_DIR / "corpus_manifest.json"
CACHE = CACHE_DIR / "corpus_embeddings.npz"


def load_corpus() -> list[tuple[str, str]]:
    """返回 [(文件名, 全文)]，按文件名排序保证可复现。"""
    return [
        (p.name, p.read_text(encoding="utf-8"))
        for p in sorted(PROJECT_ROOT.glob("*.md"))
    ]


def main(no_cache: bool = False) -> int:
    import chromadb

    t0 = time.time()
    corpus = load_corpus()
    print(f"[语料] {len(corpus)} 份 Markdown，位于 {PROJECT_ROOT}")

    splitter = ChunkingService()
    chunks: list[str] = []
    metas: list[dict] = []
    manifest: dict = {
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "embedding_model": settings.embedding_model,
        "files": {},
    }

    for name, text in corpus:
        parts = splitter.split(text)
        digest = sha1(text)
        manifest["files"][name] = {
            "sha1_16": digest[:16],
            "chars": len(text),
            "chunks": len(parts),
        }
        for i, c in enumerate(parts):
            chunks.append(c)
            metas.append({
                "filename": name,
                "chunk_index": i,
                "document_id": f"doc_{digest[:12]}",
            })
        print(f"  {name:26s} {len(text):6d} 字符 -> {len(parts):3d} 块")

    manifest["total_chunks"] = len(chunks)
    print(f"[切片] 合计 {len(chunks)} 个 chunk")

    print(f"[嵌入] 模型 {settings.embedding_model}，batch={settings.embedding_batch_size}")
    embeddings = embed_cached(chunks, CACHE, no_cache=no_cache)

    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    # 每次全量重建：chunk 数量变化后，上一轮的残留 id 会让新文档"继承"旧位置，污染指标
    try:
        client.delete_collection(COLLECTION)
        print(f"[索引] 已删除旧集合 {COLLECTION}")
    except Exception:
        pass
    col = client.create_collection(name=COLLECTION, metadata={"hnsw:space": "cosine"})
    ids = [f"{m['document_id']}_{m['chunk_index']}" for m in metas]
    col.add(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metas)

    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[完成] {COLLECTION} 共 {col.count()} 个 chunk，耗时 {time.time() - t0:.1f}s")
    print(f"[清单] {MANIFEST.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-cache", action="store_true", help="忽略嵌入缓存")
    sys.exit(main(no_cache=parser.parse_args().no_cache))
