"""Signals API route — returns user's recent signals, interests, and stored recommendation."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, desc, select

from app.core.dependencies import CurrentUser, SessionDep
from app.models import Event, Product, Recommendation, UserInterestProfile
from app.services import product_service
from app.services.interest_summary import summarise_profile

router = APIRouter(prefix="/api/signals", tags=["signals"])

# These event types carry no scoring weight and crowd out meaningful signals
# in the chip list.  They are still stored in the database for the events
# total count; they are simply excluded from the visible panel.
_EXCLUDED_EVENT_TYPES = frozenset({"scroll_depth", "category_view"})


def _relative_age(created_at: datetime) -> str:
    """Format datetime into relative age string ('just now', '12s ago', '2m ago', '1h ago')."""
    now = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    diff = max(0, int((now - created_at).total_seconds()))

    if diff < 5:
        return "just now"
    if diff < 60:
        return f"{diff}s ago"
    minutes = diff // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _format_label(event: Event, product: Product | None) -> str:
    """Build human-readable signal label server-side."""
    title = product.title if product else "Course"

    if event.event_type == "product_view":
        return f"Viewed · {title}"
    if event.event_type == "search":
        query = event.event_metadata.get("query", "")
        return f"Searched · {query}" if query else "Searched"
    if event.event_type == "time_spent":
        seconds = event.event_metadata.get("seconds")
        sec_str = f"{int(seconds)}s" if seconds else ""
        return f"Dwell · {sec_str} on {title}" if sec_str else f"Dwell on {title}"
    if event.event_type == "quick_exit":
        return f"Left quickly · {title}"
    if event.event_type in {"click", "recommendation_click"}:
        return f"Clicked · {title}"
    # Readable fallback: replace underscores, title-case, drop product suffix for events without a title.
    readable = event.event_type.replace("_", " ").title()
    return f"{readable} · {title}" if product else readable


@router.get("/recent")
def get_recent_signals(
    session: SessionDep,
    user: CurrentUser,
) -> dict:
    """Return recent signals, interest topics, and stored recommendation for the logged-in user.

    Strict invariant: Reads stored DB data ONLY. Zero LLM calls. Response in <30ms.
    """
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    # 1. Fetch last 10 *scored* events (newest first) — excludes zero-weight types
    events = session.exec(
        select(Event)
        .where(Event.user_id == user.id)
        .where(col(Event.event_type).not_in(list(_EXCLUDED_EVENT_TYPES)))
        .order_by(desc(col(Event.created_at)), desc(col(Event.id)))
        .limit(10)
    ).all()

    product_ids = {e.product_id for e in events if e.product_id is not None}
    products_by_id = {}
    if product_ids:
        prods = session.exec(
            select(Product).where(col(Product.id).in_(product_ids))
        ).all()
        products_by_id = {p.id: p for p in prods}

    events_data = []
    for event in events:
        product = products_by_id.get(event.product_id) if event.product_id else None
        events_data.append(
            {
                "id": event.id,
                "event_type": event.event_type,
                "label": _format_label(event, product),
                "age": _relative_age(event.created_at),
                "created_at": event.created_at.isoformat() if event.created_at else "",
            }
        )

    # 2. Describe the profile in one sentence.
    #    Raw topic keys, `level:` prefixes and numeric scores are developer data
    #    and stay on the Console — this endpoint feeds a user-facing panel, so
    #    it returns the readable line and nothing quantitative.
    stored_profile = session.get(UserInterestProfile, user.id)
    interest_summary = summarise_profile(
        stored_profile.profile if stored_profile else None,
        product_service.list_categories(session),
    )

    # 3. Fetch stored recommendation if present
    stored_rec = session.exec(
        select(Recommendation).where(Recommendation.user_id == user.id)
    ).first()

    rec_data = None
    if stored_rec and stored_rec.product_ids:
        # Fetch matching products preserving recommendation product_ids order
        products_by_id = {
            p.id: p
            for p in session.exec(
                select(Product).where(col(Product.id).in_(stored_rec.product_ids))
            ).all()
        }
        rec_products = [
            {
                "id": p.id,
                "title": p.title,
                "category": p.category,
                "level": p.level,
                "price": float(p.price),
                "description": p.description,
            }
            for pid in stored_rec.product_ids
            if (p := products_by_id.get(pid)) is not None
        ]
        rec_data = {
            "message": stored_rec.message,
            "product_ids": stored_rec.product_ids,
            "products": rec_products,
        }

    return {
        "events": events_data,
        "interest_summary": interest_summary,
        "recommendation": rec_data,
    }
