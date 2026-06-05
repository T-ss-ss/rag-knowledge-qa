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
    rerank_enabled: bool = False
    retrieval_multiplier: int = 3

    # Agent
    agent_max_iterations: int = 5

    # Tavily Web Search
    tavily_api_key: str = ""


settings = Settings()
