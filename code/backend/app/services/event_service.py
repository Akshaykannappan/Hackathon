"""Persistence for behavioural events.

Called from a background task, never from the request path (CONTEXT §6). The
whole batch goes in as one transaction: 20 inserts and one commit, because this
is the highest-volume write in the system.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, select

from app.core.database import engine
from app.models import Event, Product
from app.schemas.event import EVENT_TYPES, EventIn
from app.services.trigger_engine import should_generate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestResult:
    """What became of one batch."""

    stored: int
    dropped_unknown_type: int
    dropped_missing_product: int


def _existing_product_ids(session: Session, events: Sequence[EventIn]) -> set[int]:
    """Which of the referenced products still exist, in one query."""
    referenced = {e.product_id for e in events if e.product_id is not None}
    if not referenced:
        return set()
    statement = select(Product.id).where(col(Product.id).in_(referenced))
    return set(session.exec(statement).all())


def store_events(
    session: Session, user_id: int, events: Sequence[EventIn]
) -> IngestResult:
    """Insert a batch in a single transaction, dropping what cannot be stored.

    Two kinds of row are dropped rather than raised on:

    - an unrecognised `event_type`, which usually means a stale cached tracker
    - a `product_id` that no longer exists, which happens when an admin deletes
      a product while a user still has it queued. `events.product_id` is an
      enforced foreign key, so keeping these would fail the entire batch.
    """
    known_products = _existing_product_ids(session, events)

    rows: list[Event] = []
    dropped_unknown_type = 0
    dropped_missing_product = 0

    for event in events:
        if event.event_type not in EVENT_TYPES:
            dropped_unknown_type += 1
            continue
        if event.product_id is not None and event.product_id not in known_products:
            dropped_missing_product += 1
            continue

        rows.append(
            Event(
                user_id=user_id,
                event_type=event.event_type,
                product_id=event.product_id,
                # The client's own clock is preserved for latency analysis; the
                # row's `created_at` default remains the authoritative time.
                event_metadata={
                    **event.metadata,
                    "client_ts": event.occurred_at.isoformat(),
                },
            )
        )

    if rows:
        session.add_all(rows)
        session.commit()

    return IngestResult(
        stored=len(rows),
        dropped_unknown_type=dropped_unknown_type,
        dropped_missing_product=dropped_missing_product,
    )


def store_events_in_background(user_id: int, events: Sequence[EventIn]) -> None:
    """Background-task entry point: owns its own session and swallows failures.

    A request-scoped session is already closed by the time background tasks run,
    so this opens its own. Nothing here may raise: the client received its 202
    long ago and there is no one left to tell.

    Trigger evaluation runs here too, immediately after the insert. It is pure
    Python and costs no AI call, but it still belongs off the request path —
    ingest has a sub-20ms budget and nothing may be added to it (CONTEXT §6).
    """
    with Session(engine) as session:
        try:
            result = store_events(session, user_id, events)
        except SQLAlchemyError:
            session.rollback()
            logger.exception(
                "events.ingest_failed user_id=%s count=%d", user_id, len(events)
            )
            return

        logger.info(
            "events.ingested user_id=%s stored=%d dropped_unknown_type=%d "
            "dropped_missing_product=%d",
            user_id,
            result.stored,
            result.dropped_unknown_type,
            result.dropped_missing_product,
        )

        if result.stored == 0:
            # Nothing changed, so no profile can have moved.
            return

        try:
            decision = should_generate(session, user_id)
            if decision.fire:
                from app.agent.graph import run_agent

                run_agent(
                    session,
                    user_id,
                    trigger_reason=decision.reason,
                    profile=decision.profile,
                    profile_hash=decision.profile_hash,
                )
        except Exception:  # noqa: BLE001
            session.rollback()
            logger.exception("trigger.evaluation_failed user_id=%s", user_id)
