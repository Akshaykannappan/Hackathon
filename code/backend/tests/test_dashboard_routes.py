"""Tests for Dashboard and Intelligence Panel HTTP routes."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.dependencies import get_current_user, get_session
from app.main import app
from app.models import Product, User
from app.services.recommendation_service import store_recommendation


@pytest.fixture
def client(session: Session, user: User) -> TestClient:
    def _get_test_session():
        yield session

    def _get_test_user():
        return user

    app.dependency_overrides[get_session] = _get_test_session
    app.dependency_overrides[get_current_user] = _get_test_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_dashboard_cold_start_renders_without_llm(client: TestClient):
    """GET /dashboard for a new user renders cold-start spread with 0 LLM calls."""
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 200
    assert "Your Recommendations" in response.text
    assert "Cold Start Mode" in response.text


def test_dashboard_with_stored_recommendation(
    client: TestClient, user: User, products: dict[str, Product], session: Session
):
    """GET /dashboard renders stored recommendation message and product cards."""
    rec = store_recommendation(
        session,
        user.id,
        message="Persuasive copy recommending RAG and Agentic AI",
        product_ids=[products["rag"].id, products["agentic"].id],
        interest_profile={"rag": 0.8},
        trigger_reason="test",
    )

    response = client.get("/dashboard")
    assert response.status_code == 200
    assert rec.message in response.text
    assert products["rag"].title in response.text
    assert 'data-track-source="recommendation"' in response.text


def test_intelligence_panel_renders_metrics_and_runs(client: TestClient):
    """GET /intelligence renders profile, trigger state, funnel, and agent run table."""
    response = client.get("/intelligence")
    assert response.status_code == 200
    assert "Behavioural Intelligence" in response.text
    assert "Events Captured" in response.text
    assert "Mesh LLM Calls" in response.text
    assert "Retrieval Funnel" in response.text
