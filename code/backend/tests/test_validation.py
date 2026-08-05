"""Tests for agent validation, degraded run fallbacks, and hard LLM call budgets."""

import pytest
from sqlmodel import Session

from app.agent.graph import run_agent
from app.agent.nodes import validate
from app.agent.state import make_initial_state
from app.models import Product, User
from app.services.recommendation_service import store_recommendation
from tests.conftest import add_event


def test_invented_product_ids_are_rejected(session: Session, user: User):
    """Validation drops any product ID not in the reranked candidate set (CONTEXT R6)."""
    state = make_initial_state(user.id)
    state["reranked"] = [
        {"id": 10, "title": "Course 10"},
        {"id": 20, "title": "Course 20"},
    ]
    # Generator proposes 10, 20, and invented IDs 999, 888
    state["product_ids"] = [10, 999, 20, 888]
    state["message"] = "Great recommendation copy!"
    state["status"] = "ok"

    updated = validate(state)

    # Invented IDs 999 and 888 must be stripped
    assert updated["product_ids"] == [10, 20]
    assert 999 not in updated["product_ids"]
    assert 888 not in updated["product_ids"]


def test_degraded_run_preserves_previous_recommendation(
    session: Session, user: User, products: dict[str, Product]
):
    """When fewer than 2 valid IDs survive, the run degrades and retains previous recommendation."""
    # Store a initial valid recommendation
    prev_rec = store_recommendation(
        session,
        user.id,
        message="Previous good recommendation",
        product_ids=[products["rag"].id, products["agentic"].id],
        interest_profile={"rag": 0.8},
        trigger_reason="initial",
    )

    state = make_initial_state(user.id)
    state["reranked"] = [{"id": products["rag"].id, "title": "RAG Course"}]
    # Generator proposes invented IDs that fail validation
    state["product_ids"] = [9999]
    state["message"] = "Invalid recommendation proposal"
    state["status"] = "ok"

    updated = validate(state)

    # Validation marks status as degraded because < 2 valid products survived
    assert updated["status"] == "degraded"
    assert "error" in updated


def test_llm_call_budget_never_exceeds_two(
    session: Session, user: User, products: dict[str, Product]
):
    """A full agent run never executes more than 2 Mesh LLM calls (hard budget)."""
    add_event(session, user, "product_view", product=products["rag"])
    add_event(session, user, "search", metadata={"query": "agentic ai"})

    # Run agent in KeywordRetriever mode (no embedding balance needed)
    final_state = run_agent(
        session,
        user.id,
        trigger_reason="test_budget",
        profile={"rag": 0.8, "agentic_ai": 0.9},
    )

    assert final_state["llm_calls"] <= 2
