"""标注集覆盖率 + 池利用率/精排增益报告（纯本地计算，不调用任何 API）。

为什么需要这个脚本
------------------
简历/汇报里会出现两类"看起来没有出处"的数字：

1. **标注覆盖率**（37.0% → 68.8%、文档间 15%~40% 拉平到 50%~93%）
2. **候选池利用率**（92.1% / 93.0%）与**分难度精排增益**（easy/medium ≈ +27%、hard +6.7%）

第 1 类原本是临时脚本手算的，第 2 类只存在于 `metrics.json` 里要自己算比值。
面试被追问"这个数怎么来的"时，需要一个能当场跑出来的命令——本脚本就是它。

- 覆盖率：从 `eval/corpus/` 的**冻结快照**用业务切分器确定性重建 chunk
  （与 `build_index.py` 同源），再用标注的 `evidence`（原文片段）做子串匹配，
  **不依赖向量库、不调用 embedding API**
- 利用率/增益：读 `eval/results/metrics.json`，算同链路比值

用法
----
    python eval/report_coverage.py
    python eval/report_coverage.py --dataset dataset.jsonl     # 只看某一套标注
    python eval/report_coverage.py --json eval/results/coverage.json   # 另存结果
"""

import argparse
import json
import pathlib
import sys

import _common  # noqa: F401  必须最先导入：注入 CHROMA_PERSIST_DIR
from _common import EVAL_DIR, PROJECT_ROOT

from build_index import load_corpus  # noqa: E402
from app.services.chunking_service import ChunkingService  # noqa: E402

RESULTS_DIR = EVAL_DIR / "results"


def build_chunks() -> tuple[list[str], list[dict]]:
    """用业务切分器从 *.md 确定性重建 chunk（无网络、无向量库）。"""
    splitter = ChunkingService()
    chunks: list[str] = []
    metas: list[dict] = []
    for name, text in load_corpus():
        for i, c in enumerate(splitter.split(text)):
            chunks.append(c)
            metas.append({"filename": name, "chunk_index": i})
    return chunks, metas


def coverage(chunks: list[str], metas: list[dict], dataset: pathlib.Path) -> dict:
    rows = [json.loads(l) for l in
            dataset.read_text(encoding="utf-8").splitlines() if l.strip()]
    hit = [0] * len(chunks)
    unmapped: list[str] = []
    for r in rows:
        n = 0
        for i, d in enumerate(chunks):
            if r["evidence"] in d:
                hit[i] += 1
                n += 1
        if n == 0:
            unmapped.append(r["qid"])
    covered = sum(1 for c in hit if c > 0)
    per_file: dict[str, list[int]] = {}
    for i, m in enumerate(metas):
        cur = per_file.setdefault(m["filename"], [0, 0])
        cur[1] += 1
        if hit[i]:
            cur[0] += 1
    return {
        "dataset": dataset.name,
        "n_questions": len(rows),
        "n_chunks": len(chunks),
        "covered": covered,
        "uncovered": len(chunks) - covered,
        "coverage_pct": round(covered / len(chunks) * 100, 1),
        "golds_per_question": round(sum(hit) / len(rows), 2) if rows else 0.0,
        "unmapped_evidence": unmapped,
        "per_file_pct": {k: round(c / t * 100, 1) for k, (c, t) in sorted(
            per_file.items(), key=lambda kv: kv[1][0] / kv[1][1])},
    }


def pool_report(metrics_path: pathlib.Path) -> dict | None:
    """候选池利用率与分难度精排增益（都按同链路计算）。"""
    if not metrics_path.exists():
        return None
    d = json.loads(metrics_path.read_text(encoding="utf-8"))
    cfg, bd = d.get("configs", {}), d.get("by_difficulty", {})
    diffs = ("easy", "medium", "hard")
    out: dict = {"overall": {}, "by_difficulty": {}, "rerank_gain": {}}

    # 池上限档用的是自己的 k（B/F 是 k=12），故取 recall@12
    for pool, rerank, label in (("B", "C", "向量链路 C/B"), ("F", "E", "混合链路 E/F")):
        if pool in cfg and rerank in cfg:
            lo = cfg[pool].get("recall@12")
            hi = cfg[rerank].get("recall@4")
            if lo and hi:
                out["overall"][label] = round(hi / lo * 100, 1)
        if pool in bd and rerank in bd:
            out["by_difficulty"][label] = {
                x: round(bd[rerank][x]["recall@4"] / bd[pool][x]["recall@4"] * 100, 1)
                for x in diffs if x in bd[pool] and x in bd[rerank]
            }

    # 同链路对照：A->C 与 D->E
    for base, rerank, label in (("A", "C", "A→C 向量链路"), ("D", "E", "D→E 混合链路")):
        if base in bd and rerank in bd:
            out["rerank_gain"][label] = {
                x: round((bd[rerank][x]["recall@4"] - bd[base][x]["recall@4"])
                         / bd[base][x]["recall@4"] * 100, 1)
                for x in diffs if x in bd[base] and x in bd[rerank]
            }
    return out


def main(datasets: list[str], json_out: str | None) -> int:
    chunks, metas = build_chunks()
    print(f"[语料] {len(metas)} 个 chunk / "
          f"{len({m['filename'] for m in metas})} 份文档（由 *.md 确定性重建）\n")

    result: dict = {"corpus": {"chunks": len(chunks),
                               "files": len({m["filename"] for m in metas})}}
    reports = []
    for name in datasets:
        path = EVAL_DIR / name
        if not path.exists():
            print(f"[跳过] {name} 不存在")
            continue
        cov = coverage(chunks, metas, path)
        reports.append(cov)
        print(f"=== 覆盖率 · {cov['dataset']}（{cov['n_questions']} 条标注）===")
        print(f"  chunk 覆盖 {cov['covered']}/{cov['n_chunks']} = {cov['coverage_pct']}%"
              f"（空白 {cov['uncovered']}）| 平均 gold 数 {cov['golds_per_question']}")
        if cov["unmapped_evidence"]:
            print(f"  ⚠️ evidence 匹配失败的标注: {cov['unmapped_evidence']}")
        pcts = list(cov["per_file_pct"].values())
        for k, v in cov["per_file_pct"].items():
            print(f"    {k:24s} {v:5.1f}%")
        print(f"  文件间区间: {min(pcts)}% ~ {max(pcts)}%\n")
    result["coverage"] = reports

    pool = pool_report(RESULTS_DIR / "metrics.json")
    if pool:
        print("=== 候选池利用率（同链路，池上限档取 recall@12）===")
        for k, v in pool["overall"].items():
            print(f"  {k}: {v}%")
        for k, per in pool["by_difficulty"].items():
            print(f"    {k} 分层: " + "  ".join(f"{a}={b}%" for a, b in per.items()))
        print("\n=== 精排增益（同链路对照，Recall@4）===")
        for k, per in pool["rerank_gain"].items():
            print(f"  {k}: " + "  ".join(f"{a} {b:+.1f}%" for a, b in per.items()))
        print("  ⚠️ 引用时必须带链路名：A→C 的形态与 D→E 不同")
        result["pool"] = pool
    else:
        print("[跳过] eval/results/metrics.json 不存在，先跑 run_eval.py")

    if json_out:
        out = pathlib.Path(json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[输出] {out}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", action="append", default=None,
                        help="标注文件名（可重复），默认 dataset.jsonl + dataset_46_backup.jsonl")
    parser.add_argument("--json", dest="json_out", default=None, help="另存为 JSON")
    args = parser.parse_args()
    sys.exit(main(
        datasets=args.dataset or ["dataset.jsonl", "dataset_46_backup.jsonl"],
        json_out=args.json_out,
    ))
