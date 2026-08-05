"""The `agent_runs` table (docs/CONTEXT.md §5).

Not optional: this table powers the intelligence dashboard and is what proves
the efficiency claim in the README. Every trigger decision is recorded here —
the skips as well as the runs.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.models.base import utc_now, utc_timestamp_column

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_FAILED = "failed"


class AgentRun(SQLModel, table=True):
    """One evaluation of the recommendation pipeline, fired or skipped.

    `nodes` holds the per-node trace rendered by `/intelligence`: node name,
    latency, and the retrieval funnel counts (retrieved → filtered → reranked →
    recommended).

    `llm_calls` is 0 on a cache hit and at most 2 otherwise — the hard Mesh
    budget from CONTEXT §4.
    """

    __tablename__ = "agent_runs"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    trigger_reason: str = Field(max_length=255)
    nodes: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    llm_calls: int = Field(default=0)
    cache_hit: bool = Field(default=False)
    latency_ms: int = Field(default=0)
    status: str = Field(default=STATUS_OK, max_length=16)
    error: str | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=utc_timestamp_column(index=True),
    )
