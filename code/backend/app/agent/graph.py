"""LangGraph recommendation agent workflow and wiring.

Hard budget (CONTEXT §4): **exactly two Mesh LLM calls per run** — `plan_queries`
and `generate`. The refinement loop uses deterministic broadening, NOT a second
planner call, and is capped at one pass (`broadened` flag).
"""

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph
from sqlmodel import Session

from app.agent.nodes import (
    analyze_profile,
    broaden,
    cold_start,
    filter_relevance,
    generate,
    has_enough_signal,
    plan_queries,
    rerank,
    retrieve,
    store,
    validate,
)
from app.agent.state import AgentState, make_initial_state
from app.core.config import settings

logger = logging.getLogger(__name__)


def create_recommendation_graph(session: Session, trigger_reason: str = "manual"):
    """Assemble and compile the recommendation StateGraph."""
    workflow = StateGraph(AgentState)

    def _node_analyze(state: AgentState) -> dict[str, Any]:
        return analyze_profile(state, session)

    def _node_cold_start(state: AgentState) -> dict[str, Any]:
        return cold_start(state, session)

    def _node_plan_queries(state: AgentState) -> dict[str, Any]:
        return plan_queries(state)

    def _node_retrieve(state: AgentState) -> dict[str, Any]:
        return retrieve(state, session)

    def _node_filter(state: AgentState) -> dict[str, Any]:
        return filter_relevance(state)

    def _node_broaden(state: AgentState) -> dict[str, Any]:
        return broaden(state)

    def _node_rerank(state: AgentState) -> dict[str, Any]:
        return rerank(state, session)

    def _node_generate(state: AgentState) -> dict[str, Any]:
        return generate(state)

    def _node_validate(state: AgentState) -> dict[str, Any]:
        return validate(state)

    def _node_store(state: AgentState) -> dict[str, Any]:
        return store(state, session, trigger_reason=trigger_reason)

    workflow.add_node("analyze_profile", _node_analyze)
    workflow.add_node("cold_start", _node_cold_start)
    workflow.add_node("plan_queries", _node_plan_queries)
    workflow.add_node("retrieve", _node_retrieve)
    workflow.add_node("filter_relevance", _node_filter)
    workflow.add_node("broaden", _node_broaden)
    workflow.add_node("rerank", _node_rerank)
    workflow.add_node("generate", _node_generate)
    workflow.add_node("validate", _node_validate)
    workflow.add_node("store", _node_store)

    def route_after_analyze(state: AgentState) -> str:
        if not has_enough_signal(state.get("profile", {})):
            return "cold_start"
        return "plan_queries"

    def route_after_filter(state: AgentState) -> str:
        filtered = state.get("filtered", [])
        if len(filtered) < settings.retrieval_min_candidates and not state.get("broadened", False):
            return "broaden"
        return "rerank"

    workflow.add_edge(START, "analyze_profile")
    workflow.add_conditional_edges(
        "analyze_profile",
        route_after_analyze,
        {
            "cold_start": "cold_start",
            "plan_queries": "plan_queries",
        },
    )
    workflow.add_edge("cold_start", "store")
    workflow.add_edge("plan_queries", "retrieve")
    workflow.add_edge("retrieve", "filter_relevance")
    workflow.add_conditional_edges(
        "filter_relevance",
        route_after_filter,
        {
            "broaden": "broaden",
            "rerank": "rerank",
        },
    )
    workflow.add_edge("broaden", "retrieve")
    workflow.add_edge("rerank", "generate")
    workflow.add_edge("generate", "validate")
    workflow.add_edge("validate", "store")
    workflow.add_edge("store", END)

    return workflow.compile()


def run_agent(
    session: Session,
    user_id: int,
    *,
    trigger_reason: str = "manual",
    profile: dict[str, float] | None = None,
    profile_hash: str = "",
) -> AgentState:
    """Execute the recommendation graph end-to-end for a user."""
    initial_state = make_initial_state(
        user_id=user_id,
        profile=profile,
        profile_hash=profile_hash,
    )
    graph = create_recommendation_graph(session, trigger_reason=trigger_reason)
    return graph.invoke(initial_state)
