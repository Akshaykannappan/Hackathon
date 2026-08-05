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
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Create any missing tables before the first request is served."""
    init_db()
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
