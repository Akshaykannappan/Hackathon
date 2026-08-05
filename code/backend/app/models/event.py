"""The `events` table (docs/CONTEXT.md §5).

The highest-volume table in the system: the tracker flushes batches every 10
seconds or every 20 events, and ingest has a sub-20ms budget (architecture §2).
Indexes are therefore chosen for the one query the behaviour engine actually
runs — "recent events for user X" — rather than added per column.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, Index
from sqlmodel import Field, SQLModel

from app.models.base import utc_now, utc_timestamp_column


class Event(SQLModel, table=True):
    """One tracked behavioural signal.

    `event_type` is one of the weighted signals in docs/CONTEXT.md §4:
    search, product_view, time_spent, click, recommendation_click, quick_exit.

    `product_id` is nullable because searches and generic clicks are not tied to
    a product.
    """

    __tablename__ = "events"
    __table_args__ = (
        # Composite index for the behaviour engine's read pattern. Its leftmost
        # prefix also serves lookups by user_id alone, so no separate index on
        # user_id is carried — every extra index is write amplification here.
        Index("ix_events_user_id_created_at", "user_id", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id")
    event_type: str = Field(index=True, max_length=50)
    product_id: int | None = Field(default=None, foreign_key="products.id")

    # `metadata` is reserved on SQLModel/SQLAlchemy declarative classes, so the
    # attribute is renamed while the column keeps the name from CONTEXT §5.
    event_metadata: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSON, nullable=False),
    )

    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=utc_timestamp_column(index=True),
    )
