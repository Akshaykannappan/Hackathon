"""Event ingest. The one endpoint that must never be slow.

Budget: under 20ms, returning 202 (architecture §2). It parses, authorises,
hands the rows to a background task and returns — no database work happens
inside the request/response cycle.
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.core.dependencies import CurrentUser
from app.schemas.event import EventBatch
from app.services import event_service

router = APIRouter(prefix="/api/events", tags=["events"])


@router.post("/batch", status_code=status.HTTP_202_ACCEPTED)
def ingest_batch(
    batch: EventBatch,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
) -> dict[str, int]:
    """Accept a tracker flush.

    401 rather than a silent discard when signed out: the tracker already
    no-ops for anonymous visitors, so a request arriving here without a session
    means a stale cookie, and the client deserves to know.

    Batches over `MAX_BATCH_SIZE` are rejected by the schema with a 422 before
    this function runs.
    """
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to record activity.",
        )

    background_tasks.add_task(
        event_service.store_events_in_background, user.id, batch.events
    )
    return {"accepted": len(batch.events)}
