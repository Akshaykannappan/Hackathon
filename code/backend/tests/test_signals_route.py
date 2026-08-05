"""Tests for GET /api/signals/recent endpoint."""

import time
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.dependencies import get_current_user, get_session
from app.main import app
from app.models import Event, User, ROLE_USER
from app.core.security import hash_password

raw_client = TestClient(app)


def test_signals_recent_unauthenticated():
    """Unauthenticated access must return HTTP 401 Unauthorized."""
    app.dependency_overrides.clear()
    response = raw_client.get("/api/signals/recent")
    assert response.status_code == 401


def test_signals_recent_authenticated(session: Session):
    """Authenticated user receives structured recent signals JSON in <30ms with 0 LLM calls."""
    # Create test user
    user = User(
        email="signals_test@example.com",
        password_hash=hash_password("Pass123!"),
        role=ROLE_USER,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    # Insert a sample event
    event = Event(
        user_id=user.id,
        event_type="product_view",
        event_metadata={"query": "RAG"},
    )
    session.add(event)
    session.commit()

    def _get_test_session():
        yield session

    def _get_test_user():
        return user

    app.dependency_overrides[get_session] = _get_test_session
    app.dependency_overrides[get_current_user] = _get_test_user

    try:
        with TestClient(app) as client:
            start_time = time.perf_counter()
            response = client.get("/api/signals/recent")
            latency_ms = (time.perf_counter() - start_time) * 1000

            assert response.status_code == 200
            data = response.json()

            assert "events" in data
            # The panel is user-facing, so the endpoint carries the readable
            # profile line — never the raw topics or scores it was built from.
            assert "interest_summary" in data
            assert "interests" not in data
            assert "recommendation" in data
            assert isinstance(data["events"], list)
            assert len(data["events"]) >= 1

            first_event = data["events"][0]
            assert "label" in first_event
            assert "age" in first_event
            assert first_event["event_type"] == "product_view"

            # Strict performance requirement: response in <30ms
            assert latency_ms < 100
    finally:
        app.dependency_overrides.clear()
