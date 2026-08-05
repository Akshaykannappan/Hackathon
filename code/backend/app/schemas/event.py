"""The batch body posted by `tracker.js`.

Deliberately permissive about `event_type`: an unknown value is filtered out by
`event_service`, not rejected here. A user running a stale cached tracker must
not lose a whole browsing session to one unrecognised string (CONTEXT §6).
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# The weighted signals from CONTEXT §4, plus the two navigational signals the
# tracker emits for context. Anything outside this set is dropped on ingest.
EVENT_TYPES = frozenset(
    {
        "product_view",
        "search",
        "click",
        "category_view",
        "time_spent",
        "scroll_depth",
        "recommendation_click",
        "quick_exit",
    }
)

# A well-behaved client flushes at 20. This is the abuse ceiling, not the
# expected size.
MAX_BATCH_SIZE = 100


class EventIn(BaseModel):
    """One tracked signal as the browser reported it."""

    event_type: str = Field(max_length=50)
    product_id: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    # When the browser observed the event. Kept for latency analysis, but it is
    # *not* authoritative: a skewed client clock must never distort the recency
    # decay in the behaviour engine, so the row's `created_at` is set server-side.
    occurred_at: datetime


class EventBatch(BaseModel):
    """One tracker flush.

    `max_length` rejects an oversized batch during parsing, before any handler
    or database session is involved.
    """

    events: list[EventIn] = Field(min_length=1, max_length=MAX_BATCH_SIZE)
