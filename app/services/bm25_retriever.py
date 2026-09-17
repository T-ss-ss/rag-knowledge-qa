"""BM25 稀疏检索器（自实现，不引入检索框架）。

为什么需要它：稠密向量擅长语义改写（"怎么提升检索质量" ≈ "如何优化召回"），
但对**精确词面**很弱——专有名词、代码符号、编号、缩写（`BM25`、`RRF`、
`chunk_size`、`list/tuple`）常常召不回。BM25 恰好相反。两者用 RRF 融合。

为什么不用现成库：项目刻意不依赖检索/编排框架，BM25 是 40 行能写清的东西，
引入 `rank_bm25` 只是把同样的公式换个地方放。分词用 jieba（唯一新增依赖，
纯 Python 无编译产物）。

索引是内存中的，惰性构建；按集合的 chunk 数量判定失效后整表重建。
"""

import logging
import math
import re
import threading
from collections import Counter

import jieba

logger = logging.getLogger(__name__)

# 纯标点/空白 token 丢弃（jieba 会把标点单独切出来）
_PUNCT_ONLY = re.compile(r"^[\W_]+$", re.UNICODE)

# 功能词停用表。中文单字虚词（是/的/在…）在短查询里会拿到不低的 idf，
# 把"是 多少"这类噪声算进 BM25 分数，导致无关文档被顶上来。
STOPWORDS = frozenset(
    """的 了 是 在 和 与 或 及 等 我 你 他 她 它 这 那 有 无 为 对 从 到 被 把
    就 都 也 还 又 很 更 最 之 其 而 但 并 则 若 因 由 于 中 上 下 里 外 前 后
    吗 呢 啊 吧 呀 哦 嗯 一个 一些 什么 怎么 如何 哪些 哪个 这个 那个 我们 你们
    他们 可以 需要 应该 已经 不要 没有 就是 还是 或者 以及 因为 所以 但是 如果
    这样 那样 时候 一下 一直 非常 比较 可能 主要 进行 出现 使用 通过""".split()
)


def tokenize(text: str) -> list[str]:
    """jieba 分词 + 小写归一 + 去纯标点与功能词。英文/数字串保持原样。"""
    tokens = []
    for t in jieba.lcut(text):
        t = t.strip().lower()
        if not t or _PUNCT_ONLY.match(t) or t in STOPWORDS:
            continue
        tokens.append(t)
    return tokens


class BM25Index:
    """Okapi BM25 内存索引（不含查询侧缓存，缓存由 get_index 负责）。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.ids: list[str] = []
        self.documents: list[str] = []
        self.metadatas: list[dict] = []
        self._doc_len: list[int] = []
        self._avgdl: float = 0.0
        self._tf: list[Counter] = []
        self._idf: dict[str, float] = {}
        self._pos: dict[str, int] = {}

    @classmethod
    def build(
        cls,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict],
        k1: float = 1.5,
        b: float = 0.75,
    ) -> "BM25Index":
        idx = cls(k1=k1, b=b)
        idx.ids = list(ids)
        idx.documents = list(documents)
        idx.metadatas = list(metadatas)

        tokenized = [tokenize(d) for d in idx.documents]
        idx._doc_len = [len(t) for t in tokenized]
        idx._avgdl = (sum(idx._doc_len) / len(idx._doc_len)) if idx._doc_len else 0.0
        idx._tf = [Counter(t) for t in tokenized]
        idx._pos = {doc_id: i for i, doc_id in enumerate(idx.ids)}

        n = len(tokenized)
        df: Counter = Counter()
        for tokens in tokenized:
            df.update(set(tokens))
        # 概率型 idf，log 内 +1 保证非负（避免高频词拿到负分压制相关文档）
        idx._idf = {
            term: math.log(1 + (n - d + 0.5) / (d + 0.5)) for term, d in df.items()
        }
        return idx

    def search(self, query: str, top_k: int) -> list[tuple[str, float, int]]:
        """返回 [(chunk_id, bm25_score, 在该结果内的排名 0-based)]。"""
        terms = tokenize(query)
        if not terms or not self.ids:
            return []

        scores = [0.0] * len(self.ids)
        avgdl = self._avgdl or 1.0
        for term in terms:
            idf = self._idf.get(term)
            if idf is None:
                # 词表外（语料里从未出现的词）→ BM25 无法贡献，交给稠密召回
                continue
            for i, tf in enumerate(self._tf):
                f = tf.get(term)
                if not f:
                    continue
                dl = self._doc_len[i] or 1
                denom = f + self.k1 * (1 - self.b + self.b * dl / avgdl)
                scores[i] += idf * f * (self.k1 + 1) / denom

        ranked = sorted(
            zip(self.ids, scores), key=lambda t: t[1], reverse=True
        )
        hits = [(doc_id, s) for doc_id, s in ranked[:top_k] if s > 0]
        return [(doc_id, s, rank) for rank, (doc_id, s) in enumerate(hits)]

    def get(self, chunk_id: str) -> tuple[str, dict] | None:
        i = self._pos.get(chunk_id)
        if i is None:
            return None
        return self.documents[i], self.metadatas[i]


# collection_name -> (chunk 数量, 索引)
_index_cache: dict[str, tuple[int, BM25Index]] = {}
_cache_lock = threading.Lock()


def get_index(vector_store, collection_name: str) -> BM25Index | None:
    """取集合的 BM25 索引，惰性构建。

    失效判定用 chunk 数量。局限：若一次"删 N 条 + 加 N 条"使总数不变，
    索引不会重建。对当前的单文档增删场景够用；要严格正确需引入版本号/更新时间戳。
    """
    ids, documents, metadatas = vector_store.get_all_chunks(collection_name)
    count = len(ids)
    if count == 0:
        _index_cache.pop(collection_name, None)
        return None

    cached = _index_cache.get(collection_name)
    if cached is not None and cached[0] == count:
        return cached[1]

    with _cache_lock:
        cached = _index_cache.get(collection_name)
        if cached is not None and cached[0] == count:
            return cached[1]
        index = BM25Index.build(ids, documents, metadatas)
        _index_cache[collection_name] = (count, index)
        logger.info(
            "BM25 index built for '%s': %d chunks, %d terms.",
            collection_name, count, len(index._idf),
        )
        return index


def invalidate(collection_name: str | None = None) -> None:
    """显式失效缓存（增删文档后可调用；不调也会被数量变化自动发现）。"""
    with _cache_lock:
        if collection_name is None:
            _index_cache.clear()
        else:
            _index_cache.pop(collection_name, None)
