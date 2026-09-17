import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # DeepSeek Chat
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    chat_model: str = "deepseek-chat"

    # Qwen Embedding
    embedding_api_key: str = ""
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_model: str = "text-embedding-v3"

    sqlite_db_path: str = "./data/app.db"
    chroma_persist_dir: str = "./chroma_data"
    chunk_size: int = 1000
    chunk_overlap: int = 200
    max_file_size_mb: int = 50
    max_question_length: int = 2000
    default_top_k: int = 4
    # DashScope text-embedding-v3 的单次 batch 上限是 10，超过会返回 400
    # InvalidParameter。设成 20 时，任何切出 11~20 块的文档都会上传失败
    # （小块文档碰不到这个区间，所以是个很隐蔽的 bug）。
    embedding_batch_size: int = 10

    # Reranker
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    # 默认关闭：首次开启会在使用时下载模型权重（568M 参数，FP32 约 2.3 GB）。
    # 需要在 .env 中显式设置 RERANK_ENABLED=true 才会生效。
    #
    # 效果与代价（同一评测集，见 eval/results/metrics.json）：
    #   效果：Recall@4 0.677 → 0.781（+15.4%）、nDCG@4 0.675 → 0.754（+11.7%）
    #         困难题 Recall@4 0.683 → 0.817，是收益最集中的一档
    #   代价：**纯 CPU 单次 query 约 21.7 秒**（12 条候选逐对过 Cross-encoder，FP32），
    #         相对向量检索的 1.1ms 慢约 2 万倍 —— 本地演示与线上接口都不可接受。
    # 结论：CPU 环境保持关闭；有 GPU（或换 ONNX/int8 量化）时才值得开启。
    rerank_enabled: bool = False
    retrieval_multiplier: int = 3

    # 模型权重缓存目录。相对路径按【项目根】解析（不是进程工作目录），
    # 默认落在项目内 ./models —— 与 Docker 的 HF_HOME=/app/models 指向同一位置，
    # 避免权重散落到 C 盘用户目录（默认会是 ~/.cache/huggingface/hub）。
    reranker_cache_dir: str = "./models"

    # HuggingFace 下载端点。留空表示使用官方 huggingface.co；
    # 国内网络建议保留镜像，否则首次下载权重会超时。
    # 通过 huggingface_hub 的环境变量 HF_ENDPOINT 生效（见文件末尾）。
    hf_endpoint: str = "https://hf-mirror.com"

    # 混合检索：向量召回 + BM25 稀疏召回，用 RRF 融合。
    # 向量擅长语义改写，BM25 擅长专有名词/代码符号/编号等精确词面。
    #
    # 默认开启的依据（eval/results/metrics.json，46 条标注 / 173 chunk 语料）：
    #   Recall@4  0.677 → 0.745（+10.0%）；叠加精排后 0.781 → 0.812（+4.0%）
    #   候选池上限 0.855 → 0.880（混合确实多召回了正确的块）
    #   代价：单次检索 1.1ms → 24.3ms（向量检索本身耗时极低，这点增量可忽略）
    #   副作用：Hit@1 0.739 → 0.696（融合后首位命中率略降）
    # 之所以接受首位下降：RAG 把 top_k 条**全部**塞进上下文，决定成败的是
    # 召回覆盖（Recall）而非首位排序，且 nDCG@4 同步上升（0.675 → 0.710）。
    hybrid_enabled: bool = True
    # RRF 平滑常数（原论文取 60）：越大则排名差异被压得越平
    rrf_k: int = 60

    # Agent
    agent_max_iterations: int = 5

    # Tavily Web Search
    tavily_api_key: str = ""


settings = Settings()

# HuggingFace 端点必须在 huggingface_hub 被 import 之前写进环境变量，
# 而本模块是应用里最早加载的模块之一，所以放在这里设置。
# 用 setdefault：若外部已显式设置 HF_ENDPOINT，则以外部为准。
if settings.hf_endpoint:
    os.environ.setdefault("HF_ENDPOINT", settings.hf_endpoint)
