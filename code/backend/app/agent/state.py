"""Typed state container for the LangGraph recommendation agent."""

from typing import Any, Literal, TypedDict


class AgentState(TypedDict):
    """State object passed between nodes in the recommendation graph."""

    user_id: int
    profile: dict[str, float]
    profile_hash: str
    recent_signals: list[str]
    seen_product_ids: list[int]
    queries: list[str]
    retrieved: list[dict[str, Any]]
    filtered: list[dict[str, Any]]
    reranked: list[dict[str, Any]]
    broadened: bool
    message: str
    product_ids: list[int]
    llm_calls: int
    cache_hit: bool
    status: Literal["ok", "degraded", "failed"]
    error: str | None
    node_timings: dict[str, float]


def make_initial_state(
    user_id: int,
    profile: dict[str, float] | None = None,
    profile_hash: str = "",
    recent_signals: list[str] | None = None,
    seen_product_ids: list[int] | None = None,
) -> AgentState:
    """Return a fresh AgentState initialized for a recommendation run."""
    return {
        "user_id": user_id,
        "profile": profile if profile is not None else {},
        "profile_hash": profile_hash,
        "recent_signals": recent_signals if recent_signals is not None else [],
        "seen_product_ids": seen_product_ids if seen_product_ids is not None else [],
        "queries": [],
        "retrieved": [],
        "filtered": [],
        "reranked": [],
        "broadened": False,
        "message": "",
        "product_ids": [],
        "llm_calls": 0,
        "cache_hit": False,
        "status": "ok",
        "error": None,
        "node_timings": {},
    }
