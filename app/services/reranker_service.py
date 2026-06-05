import logging

from app.config import settings

logger = logging.getLogger(__name__)


class RerankerService:
    def __init__(self):
        self._model = None
        self._model_name = settings.reranker_model

    def _load_model(self):
        if self._model is not None:
            return True
        try:
            from FlagEmbedding import FlagReranker
            self._model = FlagReranker(self._model_name, use_fp16=True)
            logger.info("Reranker model '%s' loaded.", self._model_name)
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
            scores = self._model.compute_score(pairs, normalize=True)
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
            reranked_metas.append(meta)

        return reranked_docs, reranked_metas
