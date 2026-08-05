"""Whether generating a new recommendation is worth an AI call.

Pure Python, no LLM. This module is the efficiency story: it runs on every
event batch, and the overwhelming majority of those runs end in a skip that
costs zero Mesh calls. Every outcome — fire or skip — is written to
`agent_runs` with its reason, which is what the README cites and the
intelligence dashboard renders (CONTEXT §5).

Fire requires all three conditions from CONTEXT §4:

    accumulated_delta >= TRIGGER_DELTA_THRESHOLD
    AND minutes_since_last_generation >= TRIGGER_COOLDOWN_MINUTES
    AND profile_hash != stored profile_hash
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from time import perf_counter

from sqlmodel import Session

from app.core.config import settings
from app.models import STATUS_OK, AgentRun, UserInterestProfile
from app.models.base import utc_now
from app.services.behavior_engine import (
    InterestProfile,
    build_profile,
    describe_profile,
    profile_delta,
)

logger = logging.getLogger(__name__)

REASON_FIRE = "delta_threshold_met"
REASON_NO_SIGNAL = "no_signal"
REASON_PROFILE_UNCHANGED = "profile_unchanged"
REASON_BELOW_THRESHOLD = "below_delta_threshold"
REASON_COOLDOWN = "cooldown_active"


@dataclass(frozen=True)
class TriggerDecision:
    """The outcome of one evaluation, and everything that justified it."""

    fire: bool
    reason: str
    accumulated_delta: float
    profile: dict[str, float] = field(default_factory=dict)
    profile_hash: str = ""
    cache_hit: bool = False


def _cooldown_elapsed(stored: UserInterestProfile | None, now: datetime) -> bool:
    """True when enough time has passed since the last generation.

    A user who has never had a recommendation is not in cooldown.
    """
    if stored is None or stored.last_generated_at is None:
        return True
    cooldown = timedelta(minutes=settings.trigger_cooldown_minutes)
    return now - stored.last_generated_at >= cooldown


def _decide(
    snapshot: InterestProfile,
    stored: UserInterestProfile | None,
    accumulated: float,
    now: datetime,
) -> tuple[bool, str, bool]:
    """Apply the three conditions in order of cheapness. Returns (fire, reason, cache_hit)."""
    hash_unchanged = stored is not None and stored.profile_hash == snapshot.profile_hash

    # A cache hit means "the previous recommendation is still the right answer",
    # which presupposes there was a profile to recommend from.
    cache_hit = hash_unchanged and not snapshot.is_empty

    if snapshot.is_empty:
        return False, REASON_NO_SIGNAL, cache_hit
    if hash_unchanged:
        return False, REASON_PROFILE_UNCHANGED, cache_hit
    if accumulated < settings.trigger_delta_threshold:
        return False, REASON_BELOW_THRESHOLD, cache_hit
    if not _cooldown_elapsed(stored, now):
        return False, REASON_COOLDOWN, cache_hit
    return True, REASON_FIRE, cache_hit


def _persist_profile(
    session: Session,
    user_id: int,
    stored: UserInterestProfile | None,
    snapshot: InterestProfile,
    accumulated: float,
    fire: bool,
    now: datetime,
) -> None:
    """Write the current profile and the trigger state back.

    The profile and hash are stored on every evaluation, so the next delta is
    measured against what we last saw rather than against the last generation.
    `accumulated_delta` is what carries change forward across those evaluations
    until it clears the threshold.
    """
    if stored is None:
        stored = UserInterestProfile(user_id=user_id)
        session.add(stored)

    stored.profile = snapshot.profile
    stored.profile_hash = snapshot.profile_hash

    if fire:
        stored.accumulated_delta = 0.0
        stored.last_generated_at = now
    else:
        stored.accumulated_delta = accumulated

    session.add(stored)


def _record_run(
    session: Session,
    user_id: int,
    decision: TriggerDecision,
    snapshot: InterestProfile,
    latency_ms: int,
) -> None:
    """One `agent_runs` row per evaluation, skips included.

    `llm_calls` is always 0 here: the trigger engine never calls Mesh. When the
    agent runs it records its own calls against its own row, and the difference
    between these two counts is the efficiency figure.
    """
    session.add(
        AgentRun(
            user_id=user_id,
            trigger_reason=decision.reason,
            nodes=[
                {
                    "node": "trigger_evaluation",
                    "latency_ms": latency_ms,
                    "fire": decision.fire,
                    "accumulated_delta": decision.accumulated_delta,
                    "events_considered": snapshot.event_count,
                    "topics": len(snapshot.profile),
                    "top_topics": describe_profile(snapshot.profile),
                }
            ],
            llm_calls=0,
            cache_hit=decision.cache_hit,
            latency_ms=latency_ms,
            status=STATUS_OK,
        )
    )


def should_generate(
    session: Session, user_id: int, *, now: datetime | None = None
) -> TriggerDecision:
    """Evaluate whether to generate a recommendation for this user.

    Always persists the profile snapshot and always writes an `agent_runs` row,
    whatever the outcome. `now` is injectable so tests can control the cooldown
    without sleeping.
    """
    started = perf_counter()
    now = now or utc_now()

    snapshot = build_profile(session, user_id, now=now)
    stored = session.get(UserInterestProfile, user_id)

    accumulated = round(
        (stored.accumulated_delta if stored else 0.0)
        + profile_delta(stored.profile if stored else None, snapshot.profile),
        4,
    )

    fire, reason, cache_hit = _decide(snapshot, stored, accumulated, now)
    decision = TriggerDecision(
        fire=fire,
        reason=reason,
        accumulated_delta=accumulated,
        profile=snapshot.profile,
        profile_hash=snapshot.profile_hash,
        cache_hit=cache_hit,
    )

    _persist_profile(session, user_id, stored, snapshot, accumulated, fire, now)
    _record_run(
        session,
        user_id,
        decision,
        snapshot,
        int((perf_counter() - started) * 1000),
    )
    session.commit()

    logger.info(
        "trigger.evaluated user_id=%s fire=%s reason=%s delta=%.4f cache_hit=%s topics=%d",
        user_id,
        fire,
        reason,
        accumulated,
        cache_hit,
        len(snapshot.profile),
    )
    return decision
