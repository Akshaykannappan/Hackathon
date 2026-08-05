"""Centralised configuration.

Every environment key in `.env.example` is declared here. This is the only
module in the project permitted to read the environment — no `os.getenv`
anywhere else, now or later (see docs/CONTEXT.md §8).
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]   # -> code/backend


class Settings(BaseSettings):
    """Application settings, loaded from the environment or a local `.env`."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Server (read by the root `main.py` launcher) ---
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = True

    # --- Mesh API (the only permitted AI provider) ---
    mesh_api_key: str | None = None
    mesh_base_url: str = "https://api.meshapi.ai/v1"
    mesh_chat_model: str = "openai/gpt-4o-mini"
    mesh_embedding_model: str = "openai/text-embedding-3-small"

    # --- Persistence ---
    database_url: str = "sqlite:///./data/smartreco.db"
    chroma_persist_dir: str = "./data/chroma"
    chroma_collection: str = "smartreco_products"

    # --- Retrieval ---
    # "auto" probes Mesh once for embedding capability and falls back to the
    # keyword retriever when embeddings are unavailable. "chroma" and "keyword"
    # pin a backend explicitly.
    retrieval_backend: str = "auto"
    retrieval_top_k: int = 12
    retrieval_similarity_threshold: float = 0.20
    retrieval_min_candidates: int = 4

    # --- Sessions ---
    session_secret: str = "change-me"

    # --- Trigger engine ---
    trigger_delta_threshold: float = 10.0
    trigger_cooldown_minutes: int = 10

    # --- Bonus: tracing & scheduler ---
    langsmith_api_key: str | None = None
    langsmith_tracing: bool = False
    enable_scheduler: bool = False


settings = Settings()
