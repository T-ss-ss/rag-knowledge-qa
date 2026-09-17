"""检索质量评估：在同一评测集上对比多档检索配置。

为什么用纯检索指标（不调用 LLM 当裁判）
--------------------------------------
回答级指标（忠实度/相关性）需要 LLM 打分：有成本、有随机性、换模型就不可比。
检索指标（Recall / MRR / nDCG）是**确定性**的——同样的输入必得同样的分数，
所以适合放进回归测试，改一行代码就能立刻看出检索有没有变差。

配置档位设计（目的是把精排的贡献**隔离**出来）
--------------------------------------------
  A  向量 top4               rerank 关闭时的线上行为
  B  向量 top12（k=12）       候选池**上限**：gold 有没有被召进池子
  C  向量 top12 + 精排 → 4    rerank 开启时的线上行为（与 B 同一候选池）
  D  混合 top12 → 截断 4      稀疏+稠密融合，不精排
  E  混合 top12 + 精排 → 4    当前能做到的最好路径

B 的 k 是 12，与其余四档的 k=4 **不可直接比较**——它的作用是给出精排的天花板：
C 相对 B 补回的比例 = 精排把候选池里的正确答案提上来的能力。若把 B 也截断到 4，
它会在数学上退化成与 A 完全相同（同样的向量排序取前 4 条），那一档就白跑了。

用法
----
    python eval/run_eval.py                  # 全部配置
    python eval/run_eval.py --only A,C,E     # 只跑指定配置
"""

import argparse
import collections
import json
import math
import sys
import time

import _common  # noqa: F401  必须最先导入：注入 CHROMA_PERSIST_DIR
from _common import CACHE_DIR, COLLECTION, EVAL_DIR, embed_cached

from app.services import rag_pipeline  # noqa: E402
from app.services.reranker_service import RerankerService  # noqa: E402
from app.services.vector_store import VectorStoreService  # noqa: E402

DATASET = EVAL_DIR / "dataset.jsonl"
RESULTS_DIR = EVAL_DIR / "results"
TOP_K = 4

CONFIGS: dict[str, dict] = {
    "A": {"label": "向量 top4", "hybrid": False, "rerank": False, "pool": 4, "top_k": 4},
    "B": {"label": "向量 top12（候选池上限）", "hybrid": False, "rerank": False,
          "pool": 12, "top_k": 12},
    "C": {"label": "向量 top12 + 精排 → 4", "hybrid": False, "rerank": True,
          "pool": 12, "top_k": 4},
    "D": {"label": "混合 top12 → 截断4", "hybrid": True, "rerank": False,
          "pool": 12, "top_k": 4},
    "E": {"label": "混合 top12 + 精排 → 4", "hybrid": True, "rerank": True,
          "pool": 12, "top_k": 4},
    # B 与 F 是两条链路的候选池上限，k 都是 12，只用来算天花板，不参与排序质量比较
    "F": {"label": "混合 top12（候选池上限）", "hybrid": True, "rerank": False,
          "pool": 12, "top_k": 12},
}


def load_dataset(path: str | None = None) -> list[dict]:
    source = EVAL_DIR / path if path else DATASET
    rows = []
    for line in source.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_chunks(store: VectorStoreService) -> dict[str, str]:
    ids, docs, _ = store.get_all_chunks(COLLECTION)
    return dict(zip(ids, docs))


def resolve_gold(rows: list[dict], chunks: dict[str, str]) -> list[dict]:
    """把"答案原文片段"映射成 gold chunk id 集合。

    用片段而不是手写 chunk id，是为了让标注**可被机器验证**：片段找不到就说明
    标注写错了（或语料变了），脚本会直接报出来，而不是静默影响指标。
    """
    problems = []
    for r in rows:
        gold = [cid for cid, text in chunks.items() if r["evidence"] in text]
        r["gold"] = gold
        if not gold:
            problems.append((r["qid"], r["evidence"]))
    return problems


def ndcg_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    dcg = sum(
        1.0 / math.log2(i + 2) for i, cid in enumerate(ranked[:k]) if cid in gold
    )
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(gold), k)))
    return dcg / ideal if ideal else 0.0


def retrieve(cfg: dict, question: str, qvec: list[float],
             store: VectorStoreService, reranker: RerankerService) -> list[str]:
    """按给定配置检索，返回排好序的 chunk id 列表（长度 cfg['top_k']）。"""
    k = cfg["top_k"]
    if cfg["hybrid"]:
        docs, metas = rag_pipeline.hybrid_search(
            store, COLLECTION, question, qvec, cfg["pool"]
        )
    else:
        _, docs, metas = store.query_with_ids(COLLECTION, qvec, cfg["pool"])

    if cfg["rerank"] and len(docs) > k:
        docs, metas = reranker.rerank(question, docs, metas, k)
    else:
        docs, metas = docs[:k], metas[:k]

    # chunk id 可由元数据重建（build_index.py 中的构造规则）
    return [f"{m['document_id']}_{m['chunk_index']}" for m in metas]


def score(ranked: list[str], gold: set[str], k: int) -> dict:
    first = next((i for i, cid in enumerate(ranked) if cid in gold), None)
    hit_ids = [cid for cid in ranked if cid in gold]
    return {
        "recall": len(hit_ids) / len(gold),
        "hit_k": 1.0 if hit_ids else 0.0,
        "hit_1": 1.0 if ranked and ranked[0] in gold else 0.0,
        "rr": (1.0 / (first + 1)) if first is not None else 0.0,
        "ndcg": ndcg_at_k(ranked, gold, k),
    }


def main(only: list[str] | None = None, validate_only: bool = False,
         out_name: str = "metrics.json", dataset_path: str | None = None) -> int:
    rows = load_dataset(dataset_path)
    store = VectorStoreService()
    reranker = RerankerService()
    chunks = load_chunks(store)
    if not chunks:
        print("!! 评测索引为空，请先运行 python eval/build_index.py")
        return 1

    print(f"[数据] {len(rows)} 条问题 | 语料 {len(chunks)} 个 chunk")
    problems = resolve_gold(rows, chunks)
    if problems:
        print(f"\n!! 有 {len(problems)} 条标注的原文片段在语料中找不到，"
              f"这些样本已从指标中剔除：")
        for qid, ev in problems:
            print(f"     {qid}  evidence={ev!r}")
        print()
    valid = [r for r in rows if r["gold"]]
    multi = [r for r in valid if len(r["gold"]) > 1]
    print(f"[标注] 有效 {len(valid)} 条 | 多 gold {len(multi)} 条 | "
          f"平均 gold 数 {sum(len(r['gold']) for r in valid) / max(len(valid), 1):.2f}")

    if validate_only:
        # 只校验标注与语料是否对得上，不调用 embedding API
        by_cat = collections.Counter(r["category"] for r in valid)
        by_diff = collections.Counter(r["difficulty"] for r in valid)
        print("\n[类别] " + "  ".join(f"{k}={v}" for k, v in sorted(by_cat.items())))
        print("[难度] " + "  ".join(f"{k}={v}" for k, v in sorted(by_diff.items())))
        if problems:
            print(f"\n!! 请修正以上 {len(problems)} 条标注后再跑指标")
            return 1
        print("\n标注校验通过，可以跑指标。")
        return 0

    print("[嵌入] 问题向量")
    qvecs = dict(zip(
        [r["qid"] for r in valid],
        embed_cached([r["question"] for r in valid], CACHE_DIR / "query_embeddings.npz"),
    ))

    summary: dict[str, dict] = {}
    details: dict[str, list] = {}

    for key, cfg in CONFIGS.items():
        if only and key not in only:
            continue
        agg = collections.defaultdict(float)
        per_q = []
        t0 = time.perf_counter()
        for r in valid:
            t1 = time.perf_counter()
            ranked = retrieve(cfg, r["question"], qvecs[r["qid"]], store, reranker)
            dt = time.perf_counter() - t1
            s = score(ranked, set(r["gold"]), cfg["top_k"])
            for k, v in s.items():
                agg[k] += v
            agg["latency"] += dt
            gold_set = set(r["gold"])
            per_q.append({
                "qid": r["qid"], "category": r["category"], "difficulty": r["difficulty"],
                "ranked": ranked, "gold": r["gold"],
                "first_gold_rank": next(
                    (i + 1 for i, cid in enumerate(ranked) if cid in gold_set), 0),
                **{k: round(v, 4) for k, v in s.items()},
                "latency_ms": round(dt * 1000, 1),
            })
        n = len(valid)
        k = cfg["top_k"]
        summary[key] = {
            "label": cfg["label"],
            "hybrid": cfg["hybrid"],
            "rerank": cfg["rerank"],
            "pool": cfg["pool"],
            "top_k": k,
            "n": n,
            f"recall@{k}": round(agg["recall"] / n, 4),
            f"hit@{k}": round(agg["hit_k"] / n, 4),
            "hit@1": round(agg["hit_1"] / n, 4),
            f"mrr@{k}": round(agg["rr"] / n, 4),
            f"ndcg@{k}": round(agg["ndcg"] / n, 4),
            "latency_ms": round(agg["latency"] / n * 1000, 1),
        }
        details[key] = per_q
        row = summary[key]
        print(f"  [{key}] {cfg['label']:24s} k={k:<2d} "
              f"Recall@{k}={row[f'recall@{k}']:.3f} "
              f"Hit@1={row['hit@1']:.3f} "
              f"MRR@{k}={row[f'mrr@{k}']:.3f} "
              f"nDCG@{k}={row[f'ndcg@{k}']:.3f} "
              f"{row['latency_ms']:.0f}ms")

    # 按难度分层（只对 A / C / E 做，避免输出过长）
    strata: dict[str, dict] = {}
    for key in ("A", "C", "E"):
        if key not in details:
            continue
        by_diff: dict[str, list] = collections.defaultdict(list)
        for d in details[key]:
            by_diff[d["difficulty"]].append(d)
        strata[key] = {
            diff: {
                "n": len(items),
                "hit@1": round(sum(i["hit_1"] for i in items) / len(items), 4),
                "mrr@4": round(sum(i["rr"] for i in items) / len(items), 4),
                "recall@4": round(sum(i["recall"] for i in items) / len(items), 4),
            }
            for diff, items in sorted(by_diff.items())
        }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "top_k": TOP_K,
        "n_questions_total": len(rows),
        "n_questions_valid": len(valid),
        "n_multi_gold": len(multi),
        "invalid_evidence": [{"qid": q, "evidence": e} for q, e in problems],
        "corpus_chunks": len(chunks),
        "configs": summary,
        "by_difficulty": strata,
        "details": details,
    }
    (RESULTS_DIR / out_name).write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[输出] {RESULTS_DIR / out_name}")

    # 顺便打印主配置的失败样本，便于改代码时定位
    for key in ("A", "C", "E"):
        if key not in details:
            continue
        bad = [d for d in details[key] if d["recall"] < 1.0]
        if bad:
            print(f"\n[{key}] 未完全召回的样本 {len(bad)} 条：")
            for d in bad[:8]:
                print(f"   {d['qid']} rank={d['first_gold_rank'] or '-'} "
                      f"({d['difficulty']}) {d['category']}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="只跑指定配置，如 A,C,E")
    parser.add_argument(
        "--validate-only", action="store_true",
        help="只校验标注与语料是否对得上，不调用 embedding API",
    )
    parser.add_argument(
        "--out", default="metrics.json",
        help="结果文件名，写入 eval/results/。分批跑（如 --only A,B,D 与 "
             "--only C,E 分开）时用它避免互相覆盖",
    )
    parser.add_argument(
        "--dataset", default=None,
        help="标注文件名（相对 eval/），默认 dataset.jsonl。用于做同口径对照，"
             "例如用旧版标注集对比精排参数改动带来的精度变化",
    )
    args = parser.parse_args()
    sys.exit(main(
        only=[s.strip() for s in args.only.split(",") if s.strip()] or None,
        validate_only=args.validate_only,
        out_name=args.out,
        dataset_path=args.dataset,
    ))
