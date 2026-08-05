"""Engine, session dependency, and schema creation.

`DATABASE_URL` is the only knob: SQLite by default so judges need zero setup,
Postgres by changing the URL and nothing else (CONTEXT §3).
"""

from collections.abc import Generator
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import URL, Engine, make_url
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import BACKEND_DIR, settings

# Importing the package registers all six tables on SQLModel.metadata, which is
# what create_all() walks. Without this, init_db() would create nothing.
from app import models  # noqa: F401


def _resolve_url(raw_url: str) -> URL:
    """Anchor a relative SQLite path to `code/backend`, not the process CWD.

    Without this, `sqlite:///./data/smartreco.db` means a different file
    depending on where uvicorn was launched from. Non-SQLite URLs pass through
    untouched.
    """
    url = make_url(raw_url)
    if url.get_backend_name() != "sqlite":
        return url
    if not url.database or url.database == ":memory:":
        return url

    path = Path(url.database)
    if not path.is_absolute():
        path = (BACKEND_DIR / path).resolve()
    return url.set(database=str(path))


def _engine_kwargs(url: URL) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"echo": False, "pool_pre_ping": True}
    if url.get_backend_name() == "sqlite":
        # FastAPI serves requests across threads; SQLite's default guard rejects
        # a connection reused off its creating thread.
        kwargs["connect_args"] = {"check_same_thread": False}
    return kwargs


DATABASE_URL: URL = _resolve_url(settings.database_url)
engine: Engine = create_engine(DATABASE_URL, **_engine_kwargs(DATABASE_URL))


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    """SQLite ignores foreign keys unless asked, per connection."""
    if DATABASE_URL.get_backend_name() != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session scoped to one request."""
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """Create any missing tables. Idempotent — safe to run on every boot."""
    if DATABASE_URL.get_backend_name() == "sqlite" and DATABASE_URL.database:
        # The data/ directory is gitignored, so it will not exist on a fresh
        # clone and SQLite will not create it for us.
        Path(DATABASE_URL.database).parent.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)
