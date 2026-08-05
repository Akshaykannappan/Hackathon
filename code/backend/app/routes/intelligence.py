"""Intelligence dashboard route — reads stored agent_runs and profiles, 0 LLM calls."""

from fastapi import APIRouter, Request
from sqlmodel import col, desc, func, select
from starlette.responses import RedirectResponse, Response

from app.core.config import settings
from app.core.dependencies import CurrentUser, SessionDep
from app.core.templates import render
from app.models import AgentRun, Event, Product, UserInterestProfile

router = APIRouter(tags=["intelligence"])


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
    """Render the agent intelligence dashboard.

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

    # 2. Recent Signals
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

    # 3. Agent Runs & Funnel
    runs = list(
        session.exec(
            select(AgentRun)
            .where(AgentRun.user_id == user.id)
            .order_by(desc(col(AgentRun.id)))
            .limit(10)
        ).all()
    )

    latest_run = runs[0] if runs else None

    funnel = {"retrieved": 0, "filtered": 0, "reranked": 0, "recommended": 0}
    if latest_run and latest_run.nodes:
        for node_info in latest_run.nodes:
            if isinstance(node_info, dict) and "funnel" in node_info:
                funnel = node_info["funnel"]
                break

    # 4. Trigger State
    trigger_state = {
        "reason": latest_run.trigger_reason if latest_run else "no_evaluations_yet",
        "fired": latest_run.trigger_reason == "delta_threshold_met" if latest_run else False,
        "delta": stored_profile.accumulated_delta if stored_profile else 0.0,
        "threshold": settings.trigger_delta_threshold,
        "cooldown_minutes": settings.trigger_cooldown_minutes,
    }

    # 5. System Efficiency Counters
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

    return render(
        request,
        "pages/intelligence.html",
        user=user,
        interests=interests,
        signals=signals,
        trigger_state=trigger_state,
        funnel=funnel,
        efficiency={
            "events_captured": total_events,
            "llm_calls": total_llm_calls,
            "cache_hits": total_cache_hits,
        },
        runs=runs,
    )
