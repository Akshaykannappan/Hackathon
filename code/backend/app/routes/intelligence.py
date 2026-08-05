"""AI Operations Console route — reads stored agent_runs and profiles, 0 LLM calls."""

from fastapi import APIRouter, Request
from sqlmodel import col, desc, func, select
from starlette.responses import RedirectResponse, Response

from app.core.config import settings
from app.core.dependencies import CurrentUser, SessionDep
from app.core.templates import render
from app.models import AgentRun, Event, Product, UserInterestProfile

router = APIRouter(tags=["intelligence"])


PIPELINE_NODES = [
    ("analyze_profile", False),
    ("plan_queries", True),
    ("retrieve", False),
    ("filter_relevance", False),
    ("rerank", False),
    ("generate", True),
    ("validate", False),
    ("store", False),
]


def _describe_event(event: Event, product: Product | None) -> str | None:
    """Format one event into a readable plain-language signal."""
    title = f'"{product.title}"' if product else "a course"

    if event.event_type == "search":
        query = event.event_metadata.get("query", "")
        return f'searched for "{query}"' if query else None
    if event.event_type == "product_view":
        return f"viewed {title}"
    if event.event_type == "time_spent":
        seconds = event.event_metadata.get("seconds")
        return f"spent {int(seconds)}s reading {title}" if seconds else None
    if event.event_type == "quick_exit":
        return f"opened {title} and left within seconds"
    if event.event_type in {"click", "recommendation_click"}:
        return f"clicked {title}"
    if event.event_type == "category_view":
        category = event.event_metadata.get("category", "")
        return f"browsed the {category} category" if category else None
    return None


@router.get("/intelligence")
def intelligence(
    request: Request,
    session: SessionDep,
    user: CurrentUser,
) -> Response:
    """Render the AI Operations Console.

    Strict Invariant: Reads stored DB data ONLY. Zero LLM calls on GET requests.
    """
    if user is None:
        return RedirectResponse("/login", status_code=303)

    # 1. User Interest Profile
    stored_profile = session.get(UserInterestProfile, user.id)
    raw_profile = stored_profile.profile if stored_profile else {}

    interests = []
    for topic, score in sorted(raw_profile.items(), key=lambda x: abs(x[1]), reverse=True):
        interests.append(
            {
                "topic": topic,
                "score": score,
                "percentage": int(abs(score) * 100),
                "is_negative": score < 0,
            }
        )

    profile_meta = {
        "hash": stored_profile.profile_hash if stored_profile else "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "delta": stored_profile.accumulated_delta if stored_profile else 0.0,
    }

    # 2. System Efficiency Counters
    total_events = session.exec(
        select(func.count()).select_from(Event).where(Event.user_id == user.id)
    ).one()

    total_llm_calls = (
        session.exec(
            select(func.sum(AgentRun.llm_calls)).where(AgentRun.user_id == user.id)
        ).one()
        or 0
    )

    total_cache_hits = session.exec(
        select(func.count())
        .select_from(AgentRun)
        .where(AgentRun.user_id == user.id)
        .where(AgentRun.cache_hit == True)  # noqa: E712
    ).one()

    calls_per_100_events = (
        (total_llm_calls / total_events * 100.0) if total_events > 0 else 0.0
    )

    # 3. Agent Runs (Last 20)
    runs = list(
        session.exec(
            select(AgentRun)
            .where(AgentRun.user_id == user.id)
            .order_by(desc(col(AgentRun.id)))
            .limit(20)
        ).all()
    )

    latest_run = runs[0] if runs else None

    # 4. Pipeline Workflow Nodes (from latest run)
    node_timings_map = {}
    summary_data = {}
    if latest_run and latest_run.nodes:
        for item in latest_run.nodes:
            if isinstance(item, dict):
                node_name = item.get("node")
                if node_name == "summary":
                    summary_data = item
                elif node_name:
                    node_timings_map[node_name] = item.get("latency_ms", 0)

    workflow_steps = []
    for node_name, is_llm in PIPELINE_NODES:
        lat = node_timings_map.get(node_name)
        if lat is not None:
            node_state = "ran"
        elif latest_run and latest_run.status == "failed":
            node_state = "failed"
        else:
            node_state = "skipped"

        workflow_steps.append(
            {
                "name": node_name,
                "is_llm": is_llm,
                "latency_ms": lat if lat is not None else 0,
                "state": node_state,
            }
        )

    # 5. Retrieval Details (from latest run summary)
    queries = summary_data.get("queries", [])
    backend_name = summary_data.get("retrieval_backend", settings.retrieval_backend)
    funnel = summary_data.get(
        "funnel", {"retrieved": 0, "filtered": 0, "reranked": 0, "recommended": 0}
    )
    raw_candidates = summary_data.get("top_candidates", [])
    candidates = []
    for cand in raw_candidates:
        score = cand.get("score", 0.0)
        candidates.append(
            {
                "id": cand.get("id"),
                "title": cand.get("title", "Product"),
                "score": score,
                "percentage": int(min(1.0, max(0.0, score)) * 100),
            }
        )

    # 6. Mesh Routing Log (Last 20 Mesh calls / runs)
    mesh_log = []
    for r in runs[:20]:
        mesh_log.append(
            {
                "id": r.id,
                "timestamp": r.created_at.strftime("%H:%M:%S") if r.created_at else "--:--:--",
                "model": settings.mesh_chat_model,
                "llm_calls": r.llm_calls,
                "latency_ms": r.latency_ms,
                "status": r.status,
                "tokens": f"~{r.llm_calls * 280}" if r.llm_calls > 0 else "N/A",
            }
        )

    # 7. Recent Plain Language Signals
    event_rows = session.exec(
        select(Event, Product)
        .join(Product, col(Event.product_id) == Product.id, isouter=True)
        .where(Event.user_id == user.id)
        .order_by(desc(col(Event.created_at)), desc(col(Event.id)))
        .limit(20)
    ).all()

    signals: list[str] = []
    for event, product in event_rows:
        desc_text = _describe_event(event, product)
        if desc_text and desc_text not in signals:
            signals.append(desc_text)
        if len(signals) >= 7:
            break

    # 8. Trigger State
    trigger_state = {
        "reason": latest_run.trigger_reason if latest_run else "no_evaluations_yet",
        "fired": latest_run.trigger_reason in {"delta_threshold_met", "manual", "manual_force"} if latest_run else False,
        "delta": stored_profile.accumulated_delta if stored_profile else 0.0,
        "threshold": settings.trigger_delta_threshold,
        "cooldown_minutes": settings.trigger_cooldown_minutes,
    }

    return render(
        request,
        "pages/intelligence.html",
        user=user,
        interests=interests,
        profile_meta=profile_meta,
        signals=signals,
        trigger_state=trigger_state,
        funnel=funnel,
        retrieval={
            "backend": backend_name,
            "queries": queries,
            "candidates": candidates,
            "funnel": funnel,
        },
        workflow_steps=workflow_steps,
        mesh_log=mesh_log,
        efficiency={
            "events_captured": total_events,
            "llm_calls": total_llm_calls,
            "cache_hits": total_cache_hits,
            "calls_per_100_events": calls_per_100_events,
        },
        runs=runs[:15],
    )
