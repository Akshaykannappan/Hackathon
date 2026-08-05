"""The `recommendations` table (docs/CONTEXT.md §5)."""

from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.models.base import utc_now, utc_timestamp_column


class Recommendation(SQLModel, table=True):
    """A stored recommendation — what the dashboard reads.

    Recommendations are generated off the request path and persisted, so no
    user-facing request ever waits on an LLM (architecture §2). The most recent
    row for a user is also the fallback served when Mesh is unavailable
    (CONTEXT R7).

    `product_ids` holds only IDs that survived validation against the retrieved
    candidate set (CONTEXT R6). `interest_profile` is the profile snapshot at
    generation time, which is what makes a recommendation explainable later.
    """

    __tablename__ = "recommendations"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    agent_run_id: int | None = Field(default=None, foreign_key="agent_runs.id", index=True)
    message: str
    product_ids: list[int] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    interest_profile: dict[str, float] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    trigger_reason: str = Field(max_length=255)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=utc_timestamp_column(index=True),
    )
