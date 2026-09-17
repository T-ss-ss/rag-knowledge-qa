"""精排性能剖析：量化各提速手段的收益，并验证精度是否受损。

回答三个问题
------------
1. 瓶颈在哪：max_length、批处理、线程数各自影响多大？
2. 量化会不会掉精度：与 fp32 的分数漂移有多大？
3. 截断到多少 token 才划算？

结论（见 eval/README.md）：只有 int8 量化是无损的；max_length 截断会明显
拉低 Recall，不要调小。

用法：
    python eval/profile_rerank.py
"""

import time

import _common  # noqa: F401  必须最先导入
from _common import COLLECTION

import chromadb  # noqa: E402
import torch  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.reranker_service import resolve_model_path  # noqa: E402

client = chromadb.PersistentClient(path=str(_common.EVAL_DIR / ".chroma_eval"))
got = client.get_collection(COLLECTION).get(limit=12, include=["documents"])
docs = got["documents"][:12]
print(f"torch {torch.__version__} | 线程 {torch.get_num_threads()}")
print(f"样本 {len(docs)} 条 | 长度 {[len(d) for d in docs]}")

QUESTION = "混合检索里的 RRF 融合为什么比加权求和更稳？"
pairs = [[QUESTION, d] for d in docs]

from FlagEmbedding import FlagReranker  # noqa: E402

model_path = resolve_model_path()
print(f"模型：{model_path}\n")

t0 = time.perf_counter()
rk = FlagReranker(model_path, use_fp16=True)
print(f"[加载] {time.perf_counter() - t0:.1f}s")


def bench(label: str, max_length: int = 512, n: int = 2, per_pair: bool = False):
    best, scores = float("inf"), None
    for _ in range(n):
        t = time.perf_counter()
        if per_pair:
            scores = [float(rk.compute_score([p], normalize=True, max_length=max_length)[0])
                      for p in pairs]
        else:
            scores = rk.compute_score(pairs, normalize=True, max_length=max_length)
        best = min(best, time.perf_counter() - t)
    if isinstance(scores, float):
        scores = [scores]
    print(f"[{label:32s}] {best:7.2f}s ({best / len(pairs) * 1000:5.0f} ms/对) "
          f"最高分={max(scores):.4f}")
    return best, list(scores)


base_t, base_s = bench("批处理 / max_length=512")
bench("批处理 / max_length=384", max_length=384)
bench("批处理 / max_length=256", max_length=256)
bench("批处理 / max_length=128", max_length=128)
bench("逐对 12 次 / max_length=512", per_pair=True, n=1)

print("\n=== 动态 int8 量化 ===")
try:
    rk.model = torch.quantization.quantize_dynamic(
        rk.model, {torch.nn.Linear}, dtype=torch.qint8
    )
    qt, qs = bench("量化后 / max_length=512", max_length=512)
    print(f"  相对基线提速: {base_t / qt:.2f}x")
    print(f"  分数最大漂移: {max(abs(a - b) for a, b in zip(base_s, qs)):.6f}")
except Exception as e:
    print(f"  量化失败：{type(e).__name__}: {e}")

print(f"\n=== 线程数（量化后 / max_length={settings.rerank_max_length}）===")
for nt in (4, 8, 14, 20):
    torch.set_num_threads(nt)
    t = time.perf_counter()
    rk.compute_score(pairs, normalize=True, max_length=512)
    print(f"  threads={nt:2d} → {time.perf_counter() - t:6.2f}s")
