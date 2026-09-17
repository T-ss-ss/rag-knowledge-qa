"""评测脚本共用：路径、环境隔离、嵌入缓存。

为什么环境隔离要在 import 阶段完成
-----------------------------------
`app.config.settings` 在模块导入时就实例化了，之后再改环境变量不会生效。
所以 `CHROMA_PERSIST_DIR` 必须在任何 `app.*` 之前注入——把向量库指向
`eval/.chroma_eval`，业务库 `chroma_data/` 完全不受影响。
因此本模块必须在脚本里**第一个**被导入。
"""

import hashlib
import os
import pathlib
import sys

EVAL_DIR = pathlib.Path(__file__).resolve().parent
PROJECT_ROOT = EVAL_DIR.parent

os.environ["CHROMA_PERSIST_DIR"] = str(EVAL_DIR / ".chroma_eval")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np  # noqa: E402

from app.services.embedding_service import EmbeddingService  # noqa: E402

COLLECTION = "kb_eval"
CACHE_DIR = EVAL_DIR / ".cache"


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def embed_cached(
    texts: list[str],
    cache_path: pathlib.Path,
    service: EmbeddingService | None = None,
    no_cache: bool = False,
) -> list[list[float]]:
    """带磁盘缓存的嵌入：键 = sha1(模型名 + 文本)，避免重复计费。"""
    service = service or EmbeddingService()
    cache: dict[str, np.ndarray] = {}
    if cache_path.exists() and not no_cache:
        with np.load(cache_path, allow_pickle=False) as z:
            cache = {k: z[k] for k in z.files}

    keys = [sha1(f"{service.model}\x00{t}") for t in texts]
    missing = [i for i, k in enumerate(keys) if k not in cache]

    if missing:
        print(f"  新嵌入 {len(missing)}/{len(texts)} 条（其余命中缓存）")
        fresh = service.embed_texts([texts[i] for i in missing])
        for i, vec in zip(missing, fresh):
            cache[keys[i]] = np.asarray(vec, dtype=np.float32)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache_path, **cache)
    else:
        print(f"  全部 {len(texts)} 条命中缓存，未调用 API")

    return [cache[k].tolist() for k in keys]
