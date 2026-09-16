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
    embedding_batch_size: int = 20

    # Reranker
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    # 默认关闭：首次开启会在使用时下载模型权重（568M 参数，FP32 约 2.3 GB）。
    # 需要在 .env 中显式设置 RERANK_ENABLED=true 才会生效。
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
