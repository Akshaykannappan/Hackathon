"""Reading and writing stored recommendations.

The dashboard reads what already exists; nothing user-facing ever waits on the
agent (architecture §2). This module owns that stored artefact — and the "last
good recommendation" that CONTEXT R7 falls back to when Mesh is unavailable.
"""

from sqlmodel import Session, col, desc, select

from app.models import Recommendation


def latest_recommendation(session: Session, user_id: int) -> Recommendation | None:
    """The most recent stored recommendation for a user, if any.

    This is the R7 fallback: when a run degrades, the previous answer stands
    rather than the user seeing an empty dashboard.
    """
    statement = (
        select(Recommendation)
        .where(Recommendation.user_id == user_id)
        .order_by(desc(col(Recommendation.created_at)), desc(col(Recommendation.id)))
        .limit(1)
    )
    return session.exec(statement).first()


def previously_recommended_ids(
    session: Session, user_id: int, *, limit: int = 5
) -> list[int]:
    """Product IDs from recent recommendations, for the already-seen penalty."""
    statement = (
        select(Recommendation)
        .where(Recommendation.user_id == user_id)
        .order_by(desc(col(Recommendation.created_at)), desc(col(Recommendation.id)))
        .limit(limit)
    )
    seen: list[int] = []
    for recommendation in session.exec(statement).all():
        for product_id in recommendation.product_ids:
            if product_id not in seen:
                seen.append(product_id)
    return seen


def store_recommendation(
    session: Session,
    user_id: int,
    *,
    message: str,
    product_ids: list[int],
    interest_profile: dict[str, float],
    trigger_reason: str,
) -> Recommendation:
    """Persist a generated recommendation.

    Only ever called with IDs that survived validation against the retrieved
    candidate set (CONTEXT R6) — this function does not re-check, because by
    here the check has already happened and silently passing an unvalidated ID
    should be impossible rather than tolerated.
    """
    recommendation = Recommendation(
        user_id=user_id,
        message=message,
        product_ids=list(product_ids),
        interest_profile=dict(interest_profile),
        trigger_reason=trigger_reason,
    )
    session.add(recommendation)
    session.commit()
    session.refresh(recommendation)
    return recommendation
