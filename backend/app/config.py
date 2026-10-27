from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/knowledge_qa"
    upload_dir: str = "uploads"
    chroma_dir: str = "chroma_data"
    chunk_size: int = 800
    chunk_overlap: int = 100
    top_k: int = 5

    ollama_base_url: str = "http://localhost:11434"
    embed_model: str = "bge-m3"

    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/coding/v3"
    ark_api_key: str = ""
    ark_model: str = "deepseek-v4.1-flash"

    jwt_secret: str = "change-me-in-production"
    jwt_expire_hours: int = 24
    login_max_attempts: int = 5
    login_lock_minutes: int = 15


settings = Settings()
