"""SmartReco FastAPI application."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.database import init_db
from app.core.templates import STATIC_DIR
from app.routes import (
    admin,
    auth,
    catalog,
    events,
    intelligence,
    recommendations,
    signals,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Create any missing tables before the first request is served."""
    init_db()
    # Pre-warm the local ONNX embedding model so the first agent retrieval
    # does not pay the cold-load penalty (was 3,500ms; warms to <100ms).
    from app.services.vector_store import vector_store

    vector_store.warm()
    from app.tracking.scheduler import start_scheduler, stop_scheduler

    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="SmartReco", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(admin.router)
app.include_router(events.router)
app.include_router(recommendations.router)
app.include_router(intelligence.router)
app.include_router(signals.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
