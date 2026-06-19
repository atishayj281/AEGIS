from functools import lru_cache
from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    load_dotenv()
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Enterprise RAG Intelligence Platform"
    debug: bool = True
    data_dir: Path = Path("./data")
    milvus_db_path: Path = Path("./data/milvus.db")
    sqlite_path: Path = Path("./data/enterprise.db")
    audit_log_path: Path = Path("./data/audit.log")

    qdrant_url: str = "https://e3373a68-cdad-4410-88c3-488c5f5d87a5.us-west-1-0.aws.cloud.qdrant.io:6333" 
    qdrant_api_key: str = os.getenv("QDRANT_API_KEY")

    nvidia_api_key: str = os.getenv("NVIDIA_API_KEY")

    jwt_secret_key: str = "dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    max_retrieval_results: int = 8
    retrieval_timeout_seconds: float = 2.0
    query_timeout_seconds: float = 5.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
