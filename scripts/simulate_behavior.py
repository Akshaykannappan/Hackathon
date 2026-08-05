#!/usr/bin/env python3
"""Simulate realistic user browsing sessions for two distinct personas.

Exercises the full real HTTP stack (`POST /api/events/batch`).
Persona A: Data Engineer (Data Engineering, MLOps)
Persona B: Agentic-AI Learner (RAG, Agentic AI, LangGraph)

Run standalone against a running uvicorn server or direct in-memory app instance:
    python scripts/simulate_behavior.py
"""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "code" / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import httpx
from sqlmodel import Session, col, desc, select

from app.core.database import engine
from app.main import app
from app.models import AgentRun, Event, Product, Recommendation, User


def get_client() -> httpx.Client:
    """Return a client configured for live HTTP server or direct ASGI app."""
    target_url = "http://127.0.0.1:8000"
    try:
        r = httpx.get(f"{target_url}/health", timeout=1.0)
        if r.status_code == 200:
            print(f"Connecting to live server at {target_url}...")
            return httpx.Client(base_url=target_url, timeout=30.0)
    except Exception:
        pass

    from fastapi.testclient import TestClient
    print("Live server not detected at 127.0.0.1:8000. Running via in-memory TestClient...")
    return TestClient(app, base_url="http://testserver")


def ensure_user(client: httpx.Client, email: str, name: str) -> tuple[int, dict]:
    """Register or log in user and return user_id and session cookie dict."""
    from app.core.security import SESSION_COOKIE_NAME, hash_password, sign_session

    with Session(engine) as session:
        existing = session.exec(select(User).where(User.email == email)).first()
        if not existing:
            user = User(email=email, password_hash=hash_password("password123"), full_name=name)
            session.add(user)
            session.commit()
            session.refresh(user)
            user_id = user.id
        else:
            user_id = existing.id

    client.cookies.set(SESSION_COOKIE_NAME, sign_session(user_id))
    return user_id, dict(client.cookies)


def fetch_catalog_products() -> list[Product]:
    with Session(engine) as session:
        return list(session.exec(select(Product)).all())


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def simulate_persona_a(client: httpx.Client, products: list[Product]):
    print("\n=======================================================")
    print("=== PERSONA A: Data Engineer (data_engineer@test.com) ===")
    print("=======================================================")

    user_id, cookies = ensure_user(client, "data_engineer@test.com", "Data Engineer")

    # Find products matching Data & MLOps
    data_prods = [p for p in products if p.category in {"Data Engineering", "MLOps"}]
    other_prods = [p for p in products if p.category not in {"Data Engineering", "MLOps"}]

    batches = [
        # Batch 1: Initial searches and category browsing
        [
            {"event_type": "category_view", "metadata": {"category": "Data Engineering"}, "occurred_at": now_str()},
            {"event_type": "search", "metadata": {"query": "data pipeline"}, "occurred_at": now_str()},
            {"event_type": "search", "metadata": {"query": "airflow etl"}, "occurred_at": now_str()},
        ],
        # Batch 2: Viewing data engineering products
        [
            {"event_type": "product_view", "product_id": data_prods[0].id if data_prods else 1, "occurred_at": now_str()},
            {"event_type": "time_spent", "product_id": data_prods[0].id if data_prods else 1, "metadata": {"seconds": 45}, "occurred_at": now_str()},
            {"event_type": "click", "product_id": data_prods[0].id if data_prods else 1, "occurred_at": now_str()},
        ],
        # Batch 3: High engagement with MLOps & Data Pipelines
        [
            {"event_type": "search", "metadata": {"query": "mlops deployment"}, "occurred_at": now_str()},
            {"event_type": "product_view", "product_id": data_prods[1].id if len(data_prods) > 1 else 2, "occurred_at": now_str()},
            {"event_type": "time_spent", "product_id": data_prods[1].id if len(data_prods) > 1 else 2, "metadata": {"seconds": 90}, "occurred_at": now_str()},
            {"event_type": "click", "product_id": data_prods[1].id if len(data_prods) > 1 else 2, "occurred_at": now_str()},
        ],
        # Batch 4: Quick exit on non-relevant course
        [
            {"event_type": "quick_exit", "product_id": other_prods[0].id if other_prods else 3, "occurred_at": now_str()},
        ],
    ]

    for idx, batch in enumerate(batches, 1):
        resp = client.post("/api/events/batch", json={"events": batch}, cookies=cookies)
        print(f"Batch #{idx}: Posted {len(batch)} events -> Status {resp.status_code}")
        time.sleep(0.5)


def simulate_persona_b(client: httpx.Client, products: list[Product]):
    print("\n=======================================================")
    print("=== PERSONA B: Agentic AI Learner (agentic@test.com) ===")
    print("=======================================================")

    user_id, cookies = ensure_user(client, "agentic@test.com", "Agentic AI Learner")

    agentic_prods = [p for p in products if p.category in {"Agentic AI", "RAG"}]

    batches = [
        # Batch 1: RAG & Agentic searches
        [
            {"event_type": "search", "metadata": {"query": "building agentic ai"}, "occurred_at": now_str()},
            {"event_type": "search", "metadata": {"query": "rag vector search"}, "occurred_at": now_str()},
            {"event_type": "category_view", "metadata": {"category": "Agentic AI"}, "occurred_at": now_str()},
        ],
        # Batch 2: Deep reading on LangGraph and RAG
        [
            {"event_type": "product_view", "product_id": agentic_prods[0].id if agentic_prods else 1, "occurred_at": now_str()},
            {"event_type": "time_spent", "product_id": agentic_prods[0].id if agentic_prods else 1, "metadata": {"seconds": 120}, "occurred_at": now_str()},
            {"event_type": "click", "product_id": agentic_prods[0].id if agentic_prods else 1, "occurred_at": now_str()},
        ],
        # Batch 3: Additional searches and course views
        [
            {"event_type": "search", "metadata": {"query": "langgraph stateful workflows"}, "occurred_at": now_str()},
            {"event_type": "product_view", "product_id": agentic_prods[1].id if len(agentic_prods) > 1 else 2, "occurred_at": now_str()},
            {"event_type": "time_spent", "product_id": agentic_prods[1].id if len(agentic_prods) > 1 else 2, "metadata": {"seconds": 85}, "occurred_at": now_str()},
        ],
    ]

    for idx, batch in enumerate(batches, 1):
        resp = client.post("/api/events/batch", json={"events": batch}, cookies=cookies)
        print(f"Batch #{idx}: Posted {len(batch)} events -> Status {resp.status_code}")
        time.sleep(0.5)


def print_summary():
    print("\n=======================================================")
    print("=== EMPIRICAL BENCHMARK SUMMARY & AGENT RUN AUDIT ===")
    print("=======================================================")

    with Session(engine) as session:
        total_events = session.exec(select(Event)).all()
        runs = session.exec(select(AgentRun).order_by(desc(AgentRun.id))).all()
        recs = session.exec(select(Recommendation).order_by(desc(Recommendation.id))).all()

        llm_calls = sum(r.llm_calls for r in runs)
        cache_hits = sum(1 for r in runs if r.cache_hit)
        total_runs = len(runs)

        avg_latency = sum(r.latency_ms for r in runs) / total_runs if total_runs else 0.0

        print(f"Total Events Captured: {len(total_events)}")
        print(f"Total Agent Evaluations: {total_runs}")
        print(f"Total Mesh LLM Calls: {llm_calls}")
        print(f"Total Cache Hits: {cache_hits}")
        print(f"LLM Calls per 100 Events: {round((llm_calls / len(total_events) * 100) if total_events else 0.0, 2)}")
        print(f"Average Agent Latency: {round(avg_latency, 2)} ms")

        print("\n--- Recent Stored Recommendations ---")
        for r in recs[:4]:
            print(f"User #{r.user_id} [{r.trigger_reason}]: {r.message[:80]}... Products: {r.product_ids}")

        print("\n--- Agent Runs Trace ---")
        for run in runs[:10]:
            print(f"Run #{run.id} | User {run.user_id} | Reason: {run.trigger_reason} | Status: {run.status} | LLM Calls: {run.llm_calls} | Cache Hit: {run.cache_hit} | Latency: {run.latency_ms}ms")


def main():
    client = get_client()
    products = fetch_catalog_products()

    simulate_persona_a(client, products)
    simulate_persona_b(client, products)

    # Wait briefly for background tasks to settle
    time.sleep(2)
    print_summary()


if __name__ == "__main__":
    main()
