"""Shared test fixtures.

Everything runs against an in-memory SQLite database. No test touches
`data/smartreco.db`, and no test needs a network — the two modules under test
are pure Python by design (CONTEXT §9).
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

# Allows `pytest` to be run from the repository root as well as from
# code/backend, without depending on an installed package.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models import Event, Product, User, UserInterestProfile  # noqa: E402

# A fixed clock. Tests age events by subtracting from this rather than sleeping.
NOW = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(name="session")
def session_fixture():
    """A fresh, empty in-memory database per test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="user")
def user_fixture(session: Session) -> User:
    user = User(email="learner@example.com", password_hash="x")
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture(name="products")
def products_fixture(session: Session) -> dict[str, Product]:
    """One product per category, so topics are unambiguous in assertions."""
    rows = {
        "rag": Product(
            title="Retrieval-Augmented Generation from Scratch",
            description="Build a complete RAG pipeline without a framework.",
            category="RAG",
            level="intermediate",
            price=129.0,
        ),
        "agentic": Product(
            title="Building Agentic AI Systems with LangGraph",
            description="Design stateful agent graphs with explicit nodes.",
            category="Agentic AI",
            level="advanced",
            price=149.0,
        ),
        "design": Product(
            title="UX Research Methods",
            description="Choose and run the right study for the question.",
            category="Design",
            level="beginner",
            price=89.0,
        ),
    }
    for product in rows.values():
        session.add(product)
    session.commit()
    for product in rows.values():
        session.refresh(product)
    return rows


def add_event(
    session: Session,
    user: User,
    event_type: str,
    *,
    product: Product | None = None,
    metadata: dict[str, Any] | None = None,
    hours_ago: float = 0.0,
    commit: bool = True,
) -> Event:
    """Record one event at a controlled age relative to `NOW`."""
    event = Event(
        user_id=user.id,
        event_type=event_type,
        product_id=product.id if product else None,
        event_metadata=metadata or {},
        created_at=NOW - timedelta(hours=hours_ago),
    )
    session.add(event)
    if commit:
        session.commit()
        session.refresh(event)
    return event


def seed_profile(session: Session, user: User, **fields: Any) -> UserInterestProfile:
    """Put the trigger engine's stored state into a known condition."""
    stored = session.get(UserInterestProfile, user.id)
    if stored is None:
        stored = UserInterestProfile(user_id=user.id)
    for key, value in fields.items():
        setattr(stored, key, value)
    session.add(stored)
    session.commit()
    session.refresh(stored)
    return stored
