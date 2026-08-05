#!/usr/bin/env python3
"""Simulate realistic multi-persona browsing sessions.

Exercises the full real HTTP stack (POST /api/events/batch).

4 Personas:
  A — Data Engineer        : sustained Data Engineering category → fires → switches to MLOps → fires again
  B — Agentic AI Learner   : sustained RAG/Agentic category → fires → switches to LLM Foundations → fires
  C — Frontend Dev         : sustained Web Dev browsing → cache-hits dominate, one fire
  D — Security Engineer    : sustained DevOps/Security browsing → fires once

Design goals:
  - 150+ total events
  - Cache hits from sustained single-category browsing
  - Genuine interest switches that re-fire the trigger engine
  - LLM calls per 100 events well below 20 (target ≤ 10)

Run standalone:
    PYTHONPATH=code/backend python3 scripts/simulate_behavior.py

For demo mode (shorter cooldown so both phases fire):
    TRIGGER_COOLDOWN_MINUTES=1 PYTHONPATH=code/backend python3 scripts/simulate_behavior.py
"""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "code" / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import httpx
from sqlmodel import Session, col, desc, select

from app.core.config import settings
from app.core.database import engine
from app.main import app
from app.models import AgentRun, Event, Product, Recommendation, User

# How long to sleep between persona phases to let the cooldown window clear.
# The +15s margin accounts for async background task timing: the trigger fires
# in the background after HTTP 202, so last_generated_at is set a few seconds
# before the sleep starts, and we need the full cooldown to have elapsed.
_PHASE_SLEEP_SECS = max(75, (settings.trigger_cooldown_minutes * 60) + 15)


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

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
    print("Live server not detected. Running via in-memory TestClient...")
    return TestClient(app, base_url="http://testserver")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ensure_user(client: httpx.Client, email: str, name: str) -> tuple[int, dict]:
    """Register or log in user and return (user_id, cookie_dict)."""
    from app.core.security import SESSION_COOKIE_NAME, hash_password, sign_session

    with Session(engine) as session:
        existing = session.exec(select(User).where(User.email == email)).first()
        if not existing:
            user = User(
                email=email,
                password_hash=hash_password("password123"),
                full_name=name,
            )
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


def products_by_category(products: list[Product]) -> dict[str, list[Product]]:
    by_cat: dict[str, list[Product]] = {}
    for p in products:
        by_cat.setdefault(p.category, []).append(p)
    return by_cat


def post_batches(
    client: httpx.Client,
    cookies: dict,
    batches: list[list[dict]],
    label: str,
    delay: float = 0.25,
) -> None:
    for idx, batch in enumerate(batches, 1):
        resp = client.post("/api/events/batch", json={"events": batch}, cookies=cookies)
        status = resp.status_code
        print(f"  {label} batch #{idx:02d}: {len(batch):2d} events → HTTP {status}")
        time.sleep(delay)


def ev(event_type: str, product_id: int | None = None, **meta) -> dict:
    """Build a single event dict."""
    d: dict = {"event_type": event_type, "occurred_at": now_str()}
    if product_id is not None:
        d["product_id"] = product_id
    if meta:
        d["metadata"] = meta
    return d


# ---------------------------------------------------------------------------
# Persona A — Data Engineer
# Sustained Data Engineering → fires. Then switches to MLOps → fires again.
# ---------------------------------------------------------------------------

def simulate_persona_a(client: httpx.Client, by_cat: dict[str, list[Product]]) -> None:
    print("\n=================================================================")
    print("PERSONA A: Data Engineer (data_engineer@test.com)")
    print("=================================================================")
    _, cookies = ensure_user(client, "data_engineer@test.com", "Data Engineer")

    de = by_cat.get("Data Engineering", [])
    ml = by_cat.get("Machine Learning", [])

    def pid(lst: list, i: int = 0) -> int:
        return lst[i % max(len(lst), 1)].id if lst else 99

    # Phase 1: sustained Data Engineering — 5 batches (≈25 events) to cross delta
    batches_phase1 = [
        # Batch 1 — initial search + category entry
        [ev("search", query="data pipeline"), ev("search", query="airflow etl"), ev("category_view", category="Data Engineering")],
        # Batch 2 — browse and dwell
        [ev("product_view", pid(de, 0)), ev("time_spent", pid(de, 0), seconds=55), ev("click", pid(de, 0))],
        # Batch 3 — look at second course
        [ev("search", query="apache spark batch processing"), ev("product_view", pid(de, 1)), ev("time_spent", pid(de, 1), seconds=75)],
        # Batch 4 — deeper engagement (should cross delta → FIRE #1)
        [ev("product_view", pid(de, 2)), ev("time_spent", pid(de, 2), seconds=90), ev("click", pid(de, 2)), ev("search", query="dbt core production")],
        # Batch 5 — more browsing (will be skipped — already fired, profile unchanged)
        [ev("product_view", pid(de, 0)), ev("time_spent", pid(de, 0), seconds=40)],
    ]
    post_batches(client, cookies, batches_phase1, "A-phase1(DataEng)")

    print(f"  [sleeping {_PHASE_SLEEP_SECS}s for cooldown window to clear...]")
    time.sleep(_PHASE_SLEEP_SECS)

    # Phase 2: interest switch to Machine Learning — new topics, delta fires again
    batches_phase2 = [
        # Batch 6 — pivot to Machine Learning searches
        [ev("search", query="mlops model deployment"), ev("search", query="kubeflow pipelines"), ev("category_view", category="Machine Learning")],
        # Batch 7 — Machine Learning product views
        [ev("product_view", pid(ml, 0)), ev("time_spent", pid(ml, 0), seconds=110), ev("click", pid(ml, 0))],
        # Batch 8 — explicit exit from DE course (negative signal)
        [ev("quick_exit", pid(de, 0)), ev("product_view", pid(ml, 1)), ev("time_spent", pid(ml, 1), seconds=65)],
    ]
    post_batches(client, cookies, batches_phase2, "A-phase2(ML switch)")


# ---------------------------------------------------------------------------
# Persona B — Agentic AI Learner
# Sustained RAG/Agentic → fires. Then switches to LLM Foundations → fires.
# ---------------------------------------------------------------------------

def simulate_persona_b(client: httpx.Client, by_cat: dict[str, list[Product]]) -> None:
    print("\n=================================================================")
    print("PERSONA B: Agentic AI Learner (agentic@test.com)")
    print("=================================================================")
    _, cookies = ensure_user(client, "agentic@test.com", "Agentic AI Learner")

    ag = by_cat.get("Agentic AI", [])
    rag = by_cat.get("RAG", [])
    llm = by_cat.get("Machine Learning", []) or by_cat.get("Cloud", [])

    def pid(lst: list, i: int = 0) -> int:
        return lst[i % max(len(lst), 1)].id if lst else 98

    # Phase 1: sustained Agentic/RAG interest
    batches_phase1 = [
        [ev("search", query="building agentic ai"), ev("search", query="rag vector search"), ev("category_view", category="Agentic AI")],
        [ev("product_view", pid(ag, 0)), ev("time_spent", pid(ag, 0), seconds=120), ev("click", pid(ag, 0))],
        [ev("search", query="langgraph stateful workflows"), ev("product_view", pid(rag, 0)), ev("time_spent", pid(rag, 0), seconds=85)],
        # Another batch — still same topic, might fire or cache-hit
        [ev("product_view", pid(ag, 1)), ev("time_spent", pid(ag, 1), seconds=95), ev("click", pid(ag, 1))],
        # Browsing continues after first fire — below delta, skip
        [ev("product_view", pid(ag, 0)), ev("time_spent", pid(ag, 0), seconds=40)],
    ]
    post_batches(client, cookies, batches_phase1, "B-phase1(Agentic/RAG)")

    print(f"  [sleeping {_PHASE_SLEEP_SECS}s for cooldown window to clear...]")
    time.sleep(_PHASE_SLEEP_SECS)

    # Phase 2: switch to Machine Learning
    batches_phase2 = [
        [ev("search", query="llm fine tuning"), ev("search", query="prompt engineering techniques"), ev("category_view", category="Machine Learning")],
        [ev("product_view", pid(llm, 0)), ev("time_spent", pid(llm, 0), seconds=100), ev("click", pid(llm, 0))],
        [ev("product_view", pid(llm, 1)), ev("time_spent", pid(llm, 1), seconds=70)],
    ]
    post_batches(client, cookies, batches_phase2, "B-phase2(ML switch)")


# ---------------------------------------------------------------------------
# Persona C — Frontend Dev
# Sustained Web Dev category. Most batches skip (below delta / cache hit).
# One genuine fire.
# ---------------------------------------------------------------------------

def simulate_persona_c(client: httpx.Client, by_cat: dict[str, list[Product]]) -> None:
    print("\n=================================================================")
    print("PERSONA C: Frontend Developer (frontend_dev@test.com)")
    print("=================================================================")
    _, cookies = ensure_user(client, "frontend_dev@test.com", "Frontend Dev")

    web = (
        by_cat.get("Web Development", [])
        or by_cat.get("Frontend", [])
        or by_cat.get("JavaScript", [])
    )
    # Fallback: any non-engineering category
    if not web:
        web = next(
            (prods for cat, prods in by_cat.items() if "web" in cat.lower() or "front" in cat.lower()),
            list(by_cat.values())[0] if by_cat else [],
        )

    def pid(lst: list, i: int = 0) -> int:
        return lst[i % max(len(lst), 1)].id if lst else 97

    # Sustained browsing within one category — many below-delta skips expected
    batches = [
        [ev("search", query="react typescript"), ev("category_view", category="Web Development")],
        [ev("product_view", pid(web, 0)), ev("time_spent", pid(web, 0), seconds=50)],
        [ev("product_view", pid(web, 1)), ev("time_spent", pid(web, 1), seconds=45)],
        # Enough weight to cross delta — FIRE
        [ev("search", query="nextjs app router"), ev("product_view", pid(web, 2)), ev("time_spent", pid(web, 2), seconds=110), ev("click", pid(web, 2))],
        # Post-fire — same profile, below delta → skip
        [ev("product_view", pid(web, 0)), ev("time_spent", pid(web, 0), seconds=35)],
        # Still same profile — skip (cache hit scenario)
        [ev("product_view", pid(web, 1)), ev("click", pid(web, 1))],
    ]
    post_batches(client, cookies, batches, "C(Frontend)")


# ---------------------------------------------------------------------------
# Persona D — Security Engineer
# DevOps + Security browsing; one fire. Different from other personas so the
# total event volume pushes the denominator down.
# ---------------------------------------------------------------------------

def simulate_persona_d(client: httpx.Client, by_cat: dict[str, list[Product]]) -> None:
    print("\n=================================================================")
    print("PERSONA D: Security Engineer (security_eng@test.com)")
    print("=================================================================")
    _, cookies = ensure_user(client, "security_eng@test.com", "Security Engineer")

    sec = (
        by_cat.get("Security", [])
        or by_cat.get("DevSecOps", [])
        or by_cat.get("Cloud Security", [])
    )
    ops = by_cat.get("DevOps", []) or by_cat.get("Cloud", [])

    if not sec:
        all_cats = list(by_cat.keys())
        sec = by_cat.get(all_cats[-1], []) if all_cats else []
    if not ops:
        ops = sec

    def pid(lst: list, i: int = 0) -> int:
        return lst[i % max(len(lst), 1)].id if lst else 96

    batches = [
        [ev("search", query="kubernetes security hardening"), ev("category_view", category="Security")],
        [ev("product_view", pid(sec, 0)), ev("time_spent", pid(sec, 0), seconds=80), ev("click", pid(sec, 0))],
        [ev("search", query="terraform iac security"), ev("product_view", pid(ops, 0)), ev("time_spent", pid(ops, 0), seconds=60)],
        # Enough signal to cross delta — FIRE
        [ev("product_view", pid(sec, 1)), ev("time_spent", pid(sec, 1), seconds=95), ev("click", pid(sec, 1)), ev("search", query="zero trust network access")],
        # Post-fire — same profile, skip
        [ev("product_view", pid(sec, 0)), ev("time_spent", pid(sec, 0), seconds=40)],
        # One more passive batch — skip
        [ev("product_view", pid(ops, 0)), ev("time_spent", pid(ops, 0), seconds=30)],
    ]
    post_batches(client, cookies, batches, "D(Security)")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary() -> None:
    print("\n=================================================================")
    print("EMPIRICAL BENCHMARK SUMMARY")
    print("=================================================================")

    with Session(engine) as session:
        total_events = session.exec(select(Event)).all()
        runs = session.exec(select(AgentRun).order_by(desc(AgentRun.id))).all()
        recs = session.exec(select(Recommendation).order_by(desc(Recommendation.id))).all()

        llm_calls = sum(r.llm_calls for r in runs)
        cache_hits = sum(1 for r in runs if r.cache_hit)
        total_evals = len(runs)
        fired_runs = [r for r in runs if r.llm_calls > 0]
        skipped_runs = [r for r in runs if r.llm_calls == 0 and not r.cache_hit]
        cached_runs = [r for r in runs if r.cache_hit]

        n_events = len(total_events)
        ratio = round((llm_calls / n_events * 100) if n_events else 0.0, 2)

        latencies = [r.latency_ms for r in fired_runs if r.latency_ms > 0]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

        print(f"\nEvents:")
        print(f"  Total events captured         : {n_events}")
        print(f"\nTrigger Engine:")
        print(f"  Total trigger evaluations     : {total_evals}")
        print(f"  Fired (LLM calls made)        : {len(fired_runs)}")
        print(f"  Skipped (below delta)         : {len(skipped_runs)}")
        print(f"  Cache hits                    : {cache_hits} (profile unchanged)")
        print(f"\nMesh LLM Calls:")
        print(f"  Total Mesh LLM calls          : {llm_calls}")
        print(f"  LLM calls per 100 events      : {ratio}")
        print(f"\nLatency (fired runs only):")
        print(f"  Average agent run latency     : {round(avg_latency, 1)} ms")
        if latencies:
            latencies_sorted = sorted(latencies)
            p50 = latencies_sorted[len(latencies_sorted) // 2]
            p95 = latencies_sorted[int(len(latencies_sorted) * 0.95)]
            print(f"  p50 latency                   : {p50} ms")
            print(f"  p95 latency                   : {p95} ms")

        print("\n--- Recent Stored Recommendations ---")
        for r in recs[:6]:
            msg = (r.message or "")[:80]
            print(f"  User #{r.user_id} [{r.trigger_reason}]: {msg}... → {r.product_ids}")

        print("\n--- All Agent Runs ---")
        for run in runs:
            tag = "FIRE" if run.llm_calls > 0 else ("CACHE" if run.cache_hit else "SKIP")
            print(
                f"  Run #{run.id:3d} | User {run.user_id} | [{tag:5s}]"
                f" | LLM: {run.llm_calls} | Cache: {run.cache_hit}"
                f" | {run.latency_ms}ms | {run.trigger_reason}"
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    client = get_client()
    products = fetch_catalog_products()
    by_cat = products_by_category(products)

    print(f"\nCatalog: {len(products)} products across {len(by_cat)} categories")
    print("Categories:", sorted(by_cat.keys()))

    simulate_persona_a(client, by_cat)
    simulate_persona_b(client, by_cat)
    simulate_persona_c(client, by_cat)
    simulate_persona_d(client, by_cat)

    # Let background tasks settle
    time.sleep(3)
    print_summary()


if __name__ == "__main__":
    main()
