"""Weighted, time-decayed interest profiles.

Pure Python, no LLM — deliberately (CONTEXT §9). Everything here is a sum of
products, which makes it deterministic, unit-testable, and cheap enough to run
on every event batch.

    score(topic) = Σ  weight(event) × 0.5 ^ (age_hours / 6)

The output is normalised to [−1, 1]. Negative values are real and are kept:
they are what lets the reranker push away a category the user bounced off.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, col, select

from app.models import Event, Product
from app.models.base import utc_now

# CONTEXT §4. These are locked competition values — do not tune them here.
EVENT_WEIGHTS: dict[str, float] = {
    "search": 3.0,
    "product_view": 2.0,
    "time_spent": 1.5,
    "click": 1.0,
    "recommendation_click": 2.0,
    "quick_exit": -2.0,
}

# `time_spent` only counts past this dwell; a shorter visit carries no weight.
TIME_SPENT_THRESHOLD_SECONDS = 30

# Interest halves every 45 minutes / 0.75 hours.
HALF_LIFE_HOURS = 0.75

# After 7 days a signal is worth 2^-224 of its original weight, so reading
# further back is arithmetic with no effect on the result.
LOOKBACK_HOURS = 24 * 7
MAX_EVENTS = 500

# Hash and storage precision. Anything finer makes the hash unstable against
# floating-point noise and defeats the cache check.
SCORE_PRECISION = 4

# Search text handling. The minimum length is 2, not 3, because this catalog's
# most discriminating terms are short — ai, ml, ux, js, go. Grammar words are
# excluded by the stopword list instead, which is the accurate filter anyway.
MIN_TOKEN_LENGTH = 2
MAX_SEARCH_TOPICS = 5
STOPWORDS = frozenset(
    {
        "an", "as", "at", "be", "by", "do", "in", "is", "it", "me", "my",
        "of", "on", "or", "to", "up", "we",
        "and", "for", "the", "with", "from", "into", "how", "what", "why",
        "course", "courses", "tutorial", "learn", "learning", "guide",
        "intro", "introduction", "basics", "beginner", "advanced",
    }
)

LEVEL_PREFIX = "level:"

# Level topics are normalised independently of category topics so accumulated
# level scores do not depress category scores.  But independent normalisation
# makes the top level topic 1.0, identical to the top category — they tie.
# Cap level topics at this fraction of the top category score so they always
# sort below every category topic while preserving their relative order for
# the reranker's level_match term.
LEVEL_CAP = 0.5


@dataclass(frozen=True)
class InterestProfile:
    """A user's current interests, as scored from their behaviour."""

    profile: dict[str, float]
    profile_hash: str
    event_count: int
    generated_at: datetime

    @property
    def is_empty(self) -> bool:
        """True when there is not yet enough signal to personalise anything."""
        return not self.profile


def slugify(value: str) -> str:
    """Normalise a category, level or search term into a stable topic key."""
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _search_topics(query: str) -> list[str]:
    """Extract topic keys from a search query.

    Multi-word queries also yield a joined phrase key, so that searching
    "agentic ai" reinforces the same topic as the "Agentic AI" category rather
    than scattering across two unrelated tokens.
    """
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", query.lower())
        if len(token) >= MIN_TOKEN_LENGTH and token not in STOPWORDS
    ]
    topics = list(dict.fromkeys(tokens))
    if not topics:
        return []
    if len(topics) > 1:
        topics.append("_".join(topics[:MAX_SEARCH_TOPICS]))
    return topics[:MAX_SEARCH_TOPICS]


def _event_weight(event: Event) -> float:
    """The base weight of one event, before decay.

    Returns 0.0 for event types CONTEXT §4 does not weight (`category_view`,
    `scroll_depth`). They are still captured — they count towards the events
    figure in the efficiency report — they simply do not move a score.
    """
    weight = EVENT_WEIGHTS.get(event.event_type, 0.0)
    if event.event_type == "time_spent":
        seconds = event.event_metadata.get("seconds", 0)
        if not isinstance(seconds, (int, float)) or seconds <= TIME_SPENT_THRESHOLD_SECONDS:
            return 0.0
    return weight


def _decay(age_hours: float) -> float:
    """0.5 ^ (age / 0.75h). Clamped at 0 so a clock skew cannot amplify a signal."""
    return 0.5 ** (max(age_hours, 0.0) / HALF_LIFE_HOURS)


def _event_topics(event: Event, product: Product | None) -> list[str]:
    """Which topic keys one event contributes to."""
    if event.event_type == "search":
        query = event.event_metadata.get("query", "")
        return _search_topics(query) if isinstance(query, str) else []

    if product is not None:
        topics = [slugify(product.category)]
        if product.level:
            topics.append(f"{LEVEL_PREFIX}{slugify(product.level)}")
        return topics

    # A product event whose product has since been deleted, or an event type
    # that carries no subject. Nothing to attribute the weight to.
    return []


def compute_profile_hash(profile: dict[str, float]) -> str:
    """A stable fingerprint of a profile.

    Sorted keys and rounded scores, so the same interests hash identically
    across runs, processes and machines. The trigger engine compares this to
    decide whether a cached recommendation is still valid, so stability here is
    what makes the zero-Mesh-call path possible.
    """
    canonical = json.dumps(
        {key: round(value, SCORE_PRECISION) for key, value in sorted(profile.items())},
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_events(
    session: Session, user_id: int, now: datetime
) -> list[tuple[Event, Product | None]]:
    """Recent events for one user, joined to their products in a single query."""
    cutoff = now - timedelta(hours=LOOKBACK_HOURS)
    statement = (
        select(Event, Product)
        .join(Product, col(Event.product_id) == Product.id, isouter=True)
        .where(Event.user_id == user_id)
        .where(col(Event.created_at) >= cutoff)
        .order_by(col(Event.created_at).desc())
        .limit(MAX_EVENTS)
    )
    return list(session.exec(statement).all())


def build_profile(
    session: Session, user_id: int, *, now: datetime | None = None
) -> InterestProfile:
    """Score a user's current interests from their recent behaviour.

    `now` is injectable so tests can age events deterministically rather than
    sleeping.
    """
    now = now or utc_now()
    rows = _load_events(session, user_id, now)

    raw: dict[str, float] = {}
    for event, product in rows:
        weight = _event_weight(event)
        if weight == 0.0:
            continue

        topics = _event_topics(event, product)
        if not topics:
            continue

        age_hours = (now - event.created_at).total_seconds() / 3600.0
        contribution = weight * _decay(age_hours)

        # A search's weight is the search's, not each term's: splitting keeps a
        # three-word query worth the same +3.0 as a one-word query.
        if event.event_type == "search":
            contribution /= len(topics)

        for topic in topics:
            raw[topic] = raw.get(topic, 0.0) + contribution

    profile = _normalise(raw)
    return InterestProfile(
        profile=profile,
        profile_hash=compute_profile_hash(profile),
        event_count=len(rows),
        generated_at=now,
    )


def _normalise_group(group: dict[str, float]) -> dict[str, float]:
    """Scale scores within a single topic group into [−1, 1]."""
    if not group:
        return {}

    largest = max(abs(score) for score in group.values())
    if largest == 0.0:
        return {}

    return {
        topic: round(score / largest, SCORE_PRECISION)
        for topic, score in group.items()
        if round(score / largest, SCORE_PRECISION) != 0.0
    }


def _normalise(raw: dict[str, float]) -> dict[str, float]:
    """Scale scores into [−1, 1] by the largest absolute value.

    Category/search topics and level topics are normalised independently so
    accumulated level scores across different categories do not depress category
    scores or outrank the top category topic.

    After independent normalisation the top level topic would tie the top
    category topic at 1.0.  To guarantee level topics always sort below category
    topics the entire level group is scaled by LEVEL_CAP (0.5 × top category).
    """
    if not raw:
        return {}

    cat_raw = {k: v for k, v in raw.items() if not k.startswith(LEVEL_PREFIX)}
    level_raw = {k: v for k, v in raw.items() if k.startswith(LEVEL_PREFIX)}

    cat_result = _normalise_group(cat_raw)

    level_result = _normalise_group(level_raw)
    if level_result:
        # The top category score is 1.0 when any category topic exists,
        # or 0.0 for a profile containing only level topics (degenerate).
        top_cat = max(abs(v) for v in cat_result.values()) if cat_result else 1.0
        cap = top_cat * LEVEL_CAP
        level_result = {
            k: round(v * cap, SCORE_PRECISION)
            for k, v in level_result.items()
            if round(v * cap, SCORE_PRECISION) != 0.0
        }

    result = dict(cat_result)
    result.update(level_result)
    return dict(sorted(result.items()))


def profile_delta(old: dict[str, float] | None, new: dict[str, float]) -> float:
    """Σ |new − old| across the union of topics (architecture §3.3).

    A topic present in only one of the two profiles counts its full score, so
    a newly discovered interest registers as change rather than being ignored.
    """
    if not old:
        return round(sum(abs(score) for score in new.values()), SCORE_PRECISION)

    topics = set(old) | set(new)
    total = sum(abs(new.get(topic, 0.0) - old.get(topic, 0.0)) for topic in topics)
    return round(total, SCORE_PRECISION)


def describe_profile(profile: dict[str, float], *, limit: int = 5) -> list[dict[str, Any]]:
    """The strongest topics, ranked — for logging and the eventual dashboard."""
    ranked = sorted(profile.items(), key=lambda item: abs(item[1]), reverse=True)
    return [{"topic": topic, "score": score} for topic, score in ranked[:limit]]
