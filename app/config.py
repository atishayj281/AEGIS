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
    # milvus_db_path removed (Phase 4 — Milvus fully replaced by Pinecone)
    sqlite_path: Path = Path("./data/enterprise.db")
    audit_log_path: Path = Path("./data/audit.log")

    # Phase 4: Pinecone vector store
    pinecone_api_key: str = os.getenv("PINECONE_API_KEY", "")
    pinecone_index_name: str = os.getenv("PINECONE_INDEX_NAME", "aegis-documents")

    nvidia_api_key: str = os.getenv("NVIDIA_API_KEY")

    # Auth0 — used to verify RS256 JWTs issued by the frontend Auth0 tenant.
    # The frontend handles login; the backend only validates the access_token.
    auth0_domain: str = os.getenv("AUTH0_DOMAIN", "your-tenant.auth0.com")
    auth0_audience: str = os.getenv("AUTH0_AUDIENCE", "https://your-api-audience")

    # Auth0 Management API — infoDba M2M application (admin user provisioning only).
    # Required scopes on the infoDba app:
    #   create:users, update:users, delete:users, create:organization_members
    # Never hardcoded; never logged; raise RuntimeError at call time if absent.
    auth0_m2m_client_id: str = os.getenv("AUTH0_M2M_CLIENT_ID", "")
    auth0_m2m_client_secret: str = os.getenv("AUTH0_M2M_CLIENT_SECRET", "")

    # Postgres — multi-tenant relational store (Phase 2). asyncpg driver for the
    # app's async engine; Alembic swaps this to a sync driver at migration time
    # (see alembic/env.py) since autogenerate/DDL is more reliable on a sync engine.
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://aegis:1234@localhost:5432/aegis",
    )

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    max_retrieval_results: int = 8
    retrieval_timeout_seconds: float = 2.0
    query_timeout_seconds: float = 5.0

    # Conversation history settings
    conversation_max_turns: int = 20
    conversation_session_ttl_minutes: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()