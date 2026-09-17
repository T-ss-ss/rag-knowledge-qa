"""构建评测用的检索索引（与业务知识库完全隔离）。

为什么不用业务知识库当评测语料
--------------------------------
线上 `kb_default` 只有 12 个 chunk，而 reranker 的候选池默认是
`top_k × retrieval_multiplier = 4 × 3 = 12`——恰好等于全库。此时"扩大候选池"
与"不扩大候选池"会退化成同一个配置，测不出精排的贡献。所以要有一个规模
足够的语料。

评测语料
--------
`eval/corpus/` 下的 6 份 Markdown 冻结快照，约 17 万字符 → 173 个 chunk。
选它的理由：真实、可复现、无隐私问题，且内容之间存在真实的知识库常见的
语义交叉与近似重复（README / ARCHITECTURE / PROJECT_PORTFOLIO 都在讲架构）。

为什么必须是冻结快照而不是项目根目录的文档
--------------------------------------------
最初取的是 `PROJECT_ROOT.glob("*.md")`，结果踩了一个真实的可复现性坑：
跑完评测后为了同步文档又改了 `README.md` / `ARCHITECTURE.md`，
再重建索引得到的是 **174** 个 chunk（评测时是 173），
标注的 gold 集合随之漂移，`metrics.json` 里的指标再也复现不出来。

**"可复现"是这套评测体系对外的主张，所以语料必须与项目文档解耦。**
快照来源记录在 `eval/corpus/SOURCE.txt`（取自语料侧最后一次评测对应的提交）。

用法
----
    python eval/build_index.py              # 语料未变则复用嵌入缓存
    python eval/build_index.py --no-cache   # 忽略缓存，强制重新调用 API
    python eval/build_index.py --live       # 改用项目根目录的 *.md（仅调试用，会破坏可复现性）
"""

import argparse
import hashlib
import json
import sys
import time

import _common  # noqa: F401  必须最先导入：注入 CHROMA_PERSIST_DIR
from _common import CACHE_DIR, COLLECTION, EVAL_DIR, PROJECT_ROOT, embed_cached, sha1

from app.config import settings  # noqa: E402
from app.services.chunking_service import ChunkingService  # noqa: E402

MANIFEST = EVAL_DIR / "corpus_manifest.json"
CORPUS_DIR = EVAL_DIR / "corpus"
SOURCE_NOTE = CORPUS_DIR / "SOURCE.txt"
CACHE = CACHE_DIR / "corpus_embeddings.npz"


def load_corpus(live: bool = False) -> list[tuple[str, str]]:
    """返回 [(文件名, 全文)]，按文件名排序保证可复现。

    默认读 `eval/corpus/` 的冻结快照；`live=True` 时回退到项目根目录（调试用）。
    注意快照目录里**不能放 .md 文件**作说明，否则会被当成语料（说明写在 SOURCE.txt）。
    """
    root = PROJECT_ROOT if live else CORPUS_DIR
    if not live and not root.exists():
        print(f"[警告] 冻结语料 {root} 不存在，回退到项目根目录 *.md（结果不可复现）")
        root = PROJECT_ROOT
    return [
        (p.name, p.read_text(encoding="utf-8"))
        for p in sorted(root.glob("*.md"))
    ]


def main(no_cache: bool = False, live: bool = False) -> int:
    import chromadb

    t0 = time.time()
    corpus = load_corpus(live=live)
    source = "项目根目录（--live，不可复现）" if live else f"eval/corpus/ 冻结快照"
    print(f"[语料] {len(corpus)} 份 Markdown，来自 {source}")

    splitter = ChunkingService()
    chunks: list[str] = []
    metas: list[dict] = []
    manifest: dict = {
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "embedding_model": settings.embedding_model,
        "corpus": "eval/corpus (frozen)",
        "files": {},
    }
    if SOURCE_NOTE.exists() and not live:
        manifest["corpus_source"] = SOURCE_NOTE.read_text(encoding="utf-8").strip()

    for name, text in corpus:
        parts = splitter.split(text)
        # 用 sha256 而不是项目里的 sha1()：标注漂移排查时与 git 历史的哈希口径一致
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        manifest["files"][name] = {
            "sha256_16": digest[:16],
            "chars": len(text),
            "chunks": len(parts),
        }
        for i, c in enumerate(parts):
            chunks.append(c)
            metas.append({
                "filename": name,
                "chunk_index": i,
                "document_id": f"doc_{sha1(text)[:12]}",
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
    parser.add_argument("--live", action="store_true",
                        help="改用项目根目录的 *.md（调试用；会让指标与 metrics.json 不可比）")
    _args = parser.parse_args()
    sys.exit(main(no_cache=_args.no_cache, live=_args.live))
