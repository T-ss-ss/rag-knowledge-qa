import logging
import threading
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# 项目根目录：app/services/reranker_service.py -> services -> app -> 项目根
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve_cache_dir() -> Path:
    """把配置里的缓存目录解析为绝对路径。

    相对路径按【项目根】解析，而不是进程当前工作目录 —— 这样无论从哪个
    cwd 启动服务，权重都稳定落在项目内的 models/ 下，不会散到用户目录。
    """
    raw = Path(settings.reranker_cache_dir).expanduser()
    path = raw if raw.is_absolute() else _PROJECT_ROOT / raw
    path.mkdir(parents=True, exist_ok=True)
    return path


def local_model_dir() -> Path:
    """模型本地副本目录，如 models/bge-reranker-v2-m3/。"""
    return resolve_cache_dir() / settings.reranker_model.split("/")[-1]


def resolve_model_path() -> str:
    """返回加载模型时应该用的路径。

    优先使用项目内 models/<模型名>/ 的完整本地副本，而不是 HuggingFace 缓存。
    原因：hub 的缓存会在 snapshots/ 下用符号链接指向 blobs/，而 Windows 上
    没有符号链接权限时，它退化成的 0 字节占位文件会让 config.json 解析失败，
    表现为 reranker 静默降级、永远不生效。

    本地副本不存在时退回模型 ID，交由 huggingface_hub 下载到 cache_dir。
    """
    cfg = local_model_dir() / "config.json"
    if cfg.is_file() and cfg.stat().st_size > 0:
        return str(local_model_dir())
    return settings.reranker_model


class RerankerService:
    def __init__(self):
        self._model = None
        self._model_name = settings.reranker_model
        # CPU 推理，同一模型实例不应被并发调用
        self._invoke_lock = threading.Lock()
        # 量化后的实际生效标记，用于日志与排查
        self.quantized = False

    def _quantize(self) -> None:
        """对 Linear 层做动态 int8 量化。

        纯 CPU 是精排唯一的瓶颈（568M 参数、fp32、12 条候选要过一遍）。
        实测把 Linear 换成 int8 可提速约 1.86x，而分数最大漂移 < 0.001
        （见 eval/README.md 的性能表），对排序结果无可见影响。

        注意：torch.ao.quantization 在 torch 2.10 起废弃，未来需迁移到
        torchao；此处用 try/except 包住，量化失败时静默回退 fp32，
        绝不能因为一个性能优化把精排功能弄挂。
        """
        try:
            import torch

            self._model.model = torch.quantization.quantize_dynamic(
                self._model.model, {torch.nn.Linear}, dtype=torch.qint8
            )
            self.quantized = True
            logger.info("Reranker 已启用动态 int8 量化")
        except Exception as e:
            logger.warning("Reranker 量化失败，回退到 fp32：%s", e)

    def _load_model(self):
        if self._model is not None:
            return True
        try:
            from FlagEmbedding import FlagReranker

            model_path = resolve_model_path()
            cache_dir = resolve_cache_dir()
            is_local = model_path != self._model_name
            logger.info(
                "Loading reranker '%s' from %s (cache_dir=%s). %s",
                self._model_name, model_path, cache_dir,
                "本地副本" if is_local else "首次运行将下载权重，请耐心等待",
            )

            kwargs = {"use_fp16": True}
            if not is_local:
                # 只有走 Hub 时才需要 cache_dir
                kwargs["cache_dir"] = str(cache_dir)

            self._model = FlagReranker(model_path, **kwargs)
            if settings.rerank_quantize:
                self._quantize()
            logger.info(
                "Reranker model '%s' loaded (max_length=%d, quantized=%s).",
                self._model_name, settings.rerank_max_length, self.quantized,
            )
            return True
        except Exception as e:
            logger.warning("Failed to load reranker model '%s': %s", self._model_name, e)
            self._model = False
            return False

    @property
    def available(self) -> bool:
        if self._model is None:
            return self._load_model()
        return self._model is not False

    def rerank(
        self,
        question: str,
        documents: list[str],
        metadatas: list[dict],
        top_k: int,
    ) -> tuple[list[str], list[dict]]:
        if not self.available:
            return documents[:top_k], metadatas[:top_k]

        pairs = [[question, doc] for doc in documents]
        try:
            with self._invoke_lock:
                # max_length 是可调的性能旋钮：chunk 约 1000 字符（中文 ≈ 700 token），
                # 截到 256 会牺牲尾部文本，但也把注意力计算量降下来。
                scores = self._model.compute_score(
                    pairs, normalize=True, max_length=settings.rerank_max_length
                )
        except Exception as e:
            logger.warning("Rerank failed: %s, falling back to original order.", e)
            return documents[:top_k], metadatas[:top_k]

        if isinstance(scores, float):
            scores = [scores]

        scored = list(zip(documents, metadatas, scores))
        scored.sort(key=lambda x: x[2], reverse=True)

        reranked_docs = [s[0] for s in scored[:top_k]]
        reranked_metas = []
        for s in scored[:top_k]:
            meta = dict(s[1])
            meta["relevance_score"] = round(float(s[2]), 4)
            meta["score_type"] = "rerank"
            reranked_metas.append(meta)

        return reranked_docs, reranked_metas
