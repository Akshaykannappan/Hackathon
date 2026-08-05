"""The `user_interest_profiles` table (docs/CONTEXT.md §5)."""

from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.models.base import utc_timestamp_column


class UserInterestProfile(SQLModel, table=True):
    """The current behavioural profile for a user — one row per user.

    The three non-profile columns are the trigger engine's entire state
    (architecture §3.3): `accumulated_delta` against the threshold,
    `last_generated_at` against the cooldown, and `profile_hash` to detect an
    unchanged profile and serve the cached recommendation with zero Mesh calls.

    `profile` values may be negative — that is real signal, used to filter
    candidates during reranking.
    """

    __tablename__ = "user_interest_profiles"

    user_id: int = Field(foreign_key="users.id", primary_key=True)
    profile: dict[str, float] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    profile_hash: str = Field(default="", max_length=64)
    last_generated_at: datetime | None = Field(
        default=None,
        sa_column=utc_timestamp_column(nullable=True),
    )
    accumulated_delta: float = Field(default=0.0)
