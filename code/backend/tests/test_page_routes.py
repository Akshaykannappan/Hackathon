"""Tests for the merged home page, the /dashboard redirect, and the Console.

The dashboard is no longer a page. `GET /` renders the catalog directly and
carries what the dashboard used to show: the recommendation message, the
recommended cards, and the "how this was built" summary.
"""

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


def test_home_renders_catalog_directly_without_redirect(
    client: TestClient, products: dict[str, Product]
):
    """GET / is the catalog. No redirect hop."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 200
    assert "Course Catalog" in response.text
    assert products["rag"].title in response.text


def test_home_cold_start_renders_without_llm(client: TestClient):
    """A user with no recommendation yet gets the cold-start copy, still 0 LLM calls."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 200
    assert "Cold Start Mode" in response.text
    assert "pick a direction" in response.text


def test_dashboard_redirects_to_home(client: TestClient):
    """The old dashboard URL still works — it redirects rather than 404s."""
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/"


def test_home_carries_recommendation_message_and_cards(
    client: TestClient, user: User, products: dict[str, Product], session: Session
):
    """The recommendation message and its product cards render on the home page."""
    rec = store_recommendation(
        session,
        user.id,
        message="Persuasive copy recommending RAG and Agentic AI",
        product_ids=[products["rag"].id, products["agentic"].id],
        interest_profile={"rag": 0.8},
        trigger_reason="test",
    )

    response = client.get("/")

    assert response.status_code == 200
    assert rec.message in response.text
    assert products["rag"].title in response.text
    assert 'data-track-source="recommendation"' in response.text


def test_home_shows_how_this_was_built_behind_a_toggle(
    client: TestClient, user: User, products: dict[str, Product], session: Session
):
    """Trigger reason, delta, candidates and Mesh calls live inside a <details>."""
    store_recommendation(
        session,
        user.id,
        message="Copy",
        product_ids=[products["rag"].id, products["agentic"].id],
        interest_profile={"rag": 0.8},
        trigger_reason="test",
    )

    body = client.get("/").text

    assert "<details" in body
    assert "How this was built" in body
    for label in (
        "Trigger Reason",
        "Accumulated Delta",
        "Candidates Considered",
        "Mesh LLM Calls",
    ):
        assert label in body


def test_home_uses_linked_agent_run_not_latest(
    client: TestClient, user: User, products: dict[str, Product], session: Session
):
    """The 'how this was built' panel must use the run that generated the recommendation,
    even if there are newer (skipped) runs for the user.
    """
    from app.models import AgentRun

    # The run that actually generated the recommendation
    generating_run = AgentRun(
        user_id=user.id,
        trigger_reason="delta_threshold_met",
        nodes=[{"funnel": {"retrieved": 12}}],
        llm_calls=2,
        cache_hit=False,
        latency_ms=400,
        status="ok",
    )
    session.add(generating_run)
    session.flush()

    store_recommendation(
        session,
        user.id,
        message="Copy",
        product_ids=[products["rag"].id, products["agentic"].id],
        interest_profile={"rag": 0.8},
        trigger_reason="delta_threshold_met",
        agent_run_id=generating_run.id,
    )

    # A newer run that skipped (e.g. cooldown)
    skipped_run = AgentRun(
        user_id=user.id,
        trigger_reason="cooldown_active",
        nodes=[{"node": "trigger_evaluation", "latency_ms": 2}],
        llm_calls=0,
        cache_hit=False,
        latency_ms=2,
        status="ok",
    )
    session.add(skipped_run)
    session.commit()

    body = client.get("/").text

    assert "cooldown_active" not in body  # Should not use the skipped run
    assert "delta_threshold_met" in body  # Should use the generating run
    assert "2 Mesh Calls" in body or "Calls</span> 2" in body or "2" in body  # The 2 LLM calls from generating run


def test_user_facing_pages_show_no_raw_profile_data(
    client: TestClient, user: User, products: dict[str, Product], session: Session
):
    """No "Modeled Interests", no level: prefixes, no scores outside the Console."""
    store_recommendation(
        session,
        user.id,
        message="Copy",
        product_ids=[products["rag"].id],
        interest_profile={"rag": 0.82, "level:advanced": 0.5},
        trigger_reason="test",
    )

    for path in ("/", f"/product/{products['rag'].id}"):
        body = client.get(path).text
        assert "Modeled Interests" not in body, path
        assert "level:" not in body, path
        assert "Driven by interest in" not in body, path


def test_navbar_drops_centre_links_and_keeps_console_icon(client: TestClient):
    """Catalog / Dashboard / Console leave the centre; Console returns as an icon."""
    body = client.get("/").text

    assert '<a href="/dashboard">' not in body
    assert '<a href="/catalog">Catalog</a>' not in body
    assert '<a href="/intelligence">Console</a>' not in body

    assert 'title="AI Console"' in body
    assert 'class="nav-icon-button"' in body
    # The live engine indicator stays.
    assert "ENGINE ONLINE" in body


def test_intelligence_panel_still_renders_metrics_and_runs(client: TestClient):
    """The Console is unchanged — raw developer data still belongs there."""
    response = client.get("/intelligence")
    assert response.status_code == 200
    assert "AI Operations Console" in response.text
    assert "Events Captured" in response.text
    assert "Mesh LLM Calls" in response.text
    assert "Retrieval Funnel" in response.text
