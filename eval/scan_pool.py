"""候选池大小扫描：精排的延迟与候选数成正比，先量出"池子缩到多小不亏召回上限"。

思路：精排不可能召回池子里没有的东西，所以 Recall@pool 就是精排的理论天花板。
如果 pool 从 12 缩到 8 而 Recall@pool 几乎不变，说明被裁掉的 4 条里没有 gold，
缩短池子就是"免费"提速；反之会直接压低精排的上限。

只做检索、不加载精排，秒级完成。用法：
    python eval/scan_pool.py
"""

import json

import _common  # noqa: F401  必须最先导入
from _common import CACHE_DIR, COLLECTION, EVAL_DIR, embed_cached

from app.services import rag_pipeline  # noqa: E402
from app.services.vector_store import VectorStoreService  # noqa: E402

POOLS = (4, 6, 8, 10, 12, 16, 20)

rows = [json.loads(l) for l in
        (EVAL_DIR / "dataset.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
store = VectorStoreService()
ids, docs, _ = store.get_all_chunks(COLLECTION)
chunks = dict(zip(ids, docs))

valid = []
for r in rows:
    gold = [cid for cid, t in chunks.items() if r["evidence"] in t]
    if gold:
        valid.append((r, set(gold)))
print(f"[数据] {len(valid)} 条有效标注 | 语料 {len(chunks)} chunk")

qvecs = dict(zip(
    [r["qid"] for r, _ in valid],
    embed_cached([r["question"] for r, _ in valid], CACHE_DIR / "query_embeddings.npz"),
))
print()

results: dict[tuple[str, int], tuple[float, float]] = {}
for mode in ("dense", "hybrid"):
    for pool in POOLS:
        rec = hit1 = 0.0
        for r, gold in valid:
            qv = qvecs[r["qid"]]
            if mode == "hybrid":
                _, metas = rag_pipeline.hybrid_search(
                    store, COLLECTION, r["question"], qv, pool)
            else:
                _, _, metas = store.query_with_ids(COLLECTION, qv, pool)
            ranked = [f"{m['document_id']}_{m['chunk_index']}" for m in metas]
            hits = [c for c in ranked if c in gold]
            rec += len(hits) / len(gold)
            hit1 += 1.0 if hits else 0.0
        results[(mode, pool)] = (rec / len(valid), hit1 / len(valid))

d12 = results[("dense", 12)][0]
h12 = results[("hybrid", 12)][0]
print(f"{'pool':>5} | {'向量Recall@pool':>15} {'向量Hit@1':>10} | "
      f"{'混合Recall@pool':>15} {'混合Hit@1':>10} | 相对 pool=12 的上限损失")
print("-" * 98)
for pool in POOLS:
    dr, dh = results[("dense", pool)]
    hr, hh = results[("hybrid", pool)]
    print(f"{pool:>5} | {dr:>15.4f} {dh:>10.4f} | {hr:>15.4f} {hh:>10.4f} | "
          f"向量 {dr - d12:+.4f} / 混合 {hr - h12:+.4f}")
