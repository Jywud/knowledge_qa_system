from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/knowledge_qa"
    upload_dir: str = "uploads"
    chunk_size: int = 800
    chunk_overlap: int = 100
    top_k: int = 30
    rrf_top_n: int = 20
    top_n: int = 5
    embed_dim: int = 1024
    retrieval_min_score: float = 0.5
    max_history_messages: int = 20
    summary_trigger_messages: int = 30
    summary_batch_size: int = 10
    max_upload_mb: int = 50

    ollama_base_url: str = "http://localhost:11434"
    embed_model: str = "bge-m3"
    embed_provider: str = "ollama"
    embed_openai_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embed_openai_api_key: str = ""
    embed_openai_dimensions: int | None = None

    rerank_provider: str = "none"
    rerank_model: str = "gte-rerank-v2"
    rerank_api_key: str = ""
    rerank_base_url: str = "https://dashscope.aliyuncs.com"

    llm_base_url: str = "https://ark.cn-beijing.volces.com/api/coding/v3"
    llm_api_key: str = ""
    llm_model: str = "deepseek-v4.1-flash"

    jwt_secret: str = "change-me-in-production"
    jwt_expire_hours: int = 24
    login_max_attempts: int = 5
    login_lock_minutes: int = 15
    trusted_proxy_ips: str = "127.0.0.1,::1"


settings = Settings()
