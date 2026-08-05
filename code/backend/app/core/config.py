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
    embedding_backend: str = "auto"
    retrieval_top_k: int = 12
    retrieval_similarity_threshold: float = 0.30
    retrieval_min_candidates: int = 4

    # --- Sessions ---
    session_secret: str = "change-me"

    # --- Trigger engine ---
    # With HALF_LIFE_HOURS=0.75 and normalised scores in [−1, 1], a focused
    # 90-second browsing session accumulates a first-batch delta of ~1.5 (one
    # new category at 1.0 + one level topic at 0.5).  A threshold of 2.0 fires
    # after the profile is established (category + level + search reinforcement)
    # and prevents firing on a single product view alone.
    trigger_delta_threshold: float = 2.0
    trigger_cooldown_minutes: int = 10

    # --- Bonus: tracing & scheduler ---
    langsmith_api_key: str | None = None
    langsmith_tracing: bool = False
    enable_scheduler: bool = False


settings = Settings()

if settings.langsmith_tracing and settings.langsmith_api_key:
    import os

    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = "smartreco"
