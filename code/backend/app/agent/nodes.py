"""The graph's nodes. Two of them call Mesh; the rest are deterministic Python.

Budget (CONTEXT §4): **exactly two Mesh chat calls per run** — `plan_queries`
and `generate`. Everything else here is arithmetic and SQL. The refinement loop
broadens deterministically rather than asking the model to re-plan, which is
what keeps the budget intact while leaving the graph genuinely adaptive
(architecture §3.4).

Every node stamps its own elapsed time into `node_timings`, which is what the
`agent_runs` trace is built from.
"""

import logging
from functools import wraps
from time import perf_counter
from typing import Any, Callable

from sqlmodel import Session, col, desc, select

from app.agent.state import AgentState
from app.ai.mesh_client import MeshUnavailableError, mesh_client
from app.ai.prompts import build_generator_prompt, build_query_planner_prompt
from app.core.config import settings
from app.models import AgentRun, Event, Product
from app.services import recommendation_service
from app.services.behavior_engine import (
    LEVEL_PREFIX,
    build_profile,
    slugify,
)
from app.services.retrieval import get_retriever

logger = logging.getLogger(__name__)

# --- Cold start (architecture §5) -------------------------------------------
# Below this much accumulated positive signal the agent has nothing personal to
# say, so it says so honestly and spends nothing.
COLD_START_MIN_TOPICS = 2
COLD_START_MIN_SIGNAL = 1.0
COLD_START_CATEGORIES = 6
COLD_START_MESSAGE = (
    "SmartReco doesn't know you yet — pick a direction. "
    "Here's a spread across the catalog: open anything that looks interesting, "
    "and the recommendations below will start shaping themselves around what "
    "you actually do."
)
COLD_START_REASON = "cold_start"

# --- Retrieval and generation shape ------------------------------------------
MAX_QUERIES = 3
MAX_CANDIDATES_TO_GENERATOR = 8
MIN_VALID_PRODUCTS = 2
MAX_RECOMMENDED_PRODUCTS = 3
RECENT_SIGNAL_LIMIT = 5
RECENCY_WINDOW_EVENTS = 10

# --- Reranking weights (architecture §3.5) -----------------------------------
W_SEMANTIC = 1.00
W_INTEREST = 0.80
W_RECENCY = 0.30
W_LEVEL = 0.40
W_NEGATIVE = 0.60
W_SEEN = 0.50


def timed(name: str) -> Callable:
    """Record a node's wall time into `node_timings` without it having to care."""

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(state: AgentState, *args: Any, **kwargs: Any) -> dict[str, Any]:
            started = perf_counter()
            result = fn(state, *args, **kwargs) or {}
            elapsed = round((perf_counter() - started) * 1000, 2)
            return {
                **result,
                "node_timings": {
                    **state.get("node_timings", {}),
                    **result.get("node_timings", {}),
                    name: elapsed,
                },
            }

        return wrapper

    return decorator


# ---------------------------------------------------------------- helpers


def _positive_topics(profile: dict[str, float]) -> dict[str, float]:
    """Category topics with positive scores. Level keys are not search terms."""
    return {
        topic: score
        for topic, score in profile.items()
        if score > 0 and not topic.startswith(LEVEL_PREFIX)
    }


def has_enough_signal(profile: dict[str, float]) -> bool:
    """Whether there is enough behaviour to personalise, or we are cold."""
    positives = _positive_topics(profile)
    return (
        len(positives) >= COLD_START_MIN_TOPICS
        and sum(positives.values()) >= COLD_START_MIN_SIGNAL
    )


def _describe_event(event: Event, product: Product | None) -> str | None:
    """One behavioural signal, in the plain language the generator prompt wants."""
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
        return f"clicked through to {title}"
    if event.event_type == "category_view":
        category = event.event_metadata.get("category", "")
        return f"browsed the {category} category" if category else None
    return None


def _recent_rows(
    session: Session, user_id: int, limit: int
) -> list[tuple[Event, Product | None]]:
    statement = (
        select(Event, Product)
        .join(Product, col(Event.product_id) == Product.id, isouter=True)
        .where(Event.user_id == user_id)
        .order_by(desc(col(Event.created_at)), desc(col(Event.id)))
        .limit(limit)
    )
    return list(session.exec(statement).all())


def _fallback_queries(profile: dict[str, float]) -> list[str]:
    """Queries derived from the profile with no LLM involved.

    Used when the planner call fails, and as the seed for deterministic
    broadening. Topic keys are slugs, so underscores become spaces again.
    """
    ranked = sorted(_positive_topics(profile).items(), key=lambda kv: kv[1], reverse=True)
    return [topic.replace("_", " ") for topic, _ in ranked[:MAX_QUERIES]]


# ------------------------------------------------------------------- nodes


@timed("analyze_profile")
def analyze_profile(state: AgentState, session: Session) -> dict[str, Any]:
    """Load the profile, recent signals and the already-seen set. Pure Python."""
    profile = state.get("profile") or {}
    profile_hash = state.get("profile_hash", "")

    if not profile:
        snapshot = build_profile(session, state["user_id"])
        profile, profile_hash = snapshot.profile, snapshot.profile_hash

    rows = _recent_rows(session, state["user_id"], RECENT_SIGNAL_LIMIT * 3)

    signals: list[str] = []
    for event, product in rows:
        described = _describe_event(event, product)
        if described and described not in signals:
            signals.append(described)
        if len(signals) >= RECENT_SIGNAL_LIMIT:
            break

    seen = [product.id for _, product in rows if product is not None]
    seen += recommendation_service.previously_recommended_ids(session, state["user_id"])

    return {
        "profile": profile,
        "profile_hash": profile_hash,
        "recent_signals": signals,
        "seen_product_ids": list(dict.fromkeys(seen)),
    }


@timed("cold_start")
def cold_start(state: AgentState, session: Session) -> dict[str, Any]:
    """Diverse picks across categories, zero LLM calls (architecture §5).

    Deterministic by construction: the cheapest beginner course in each
    category, categories in alphabetical order. A new user gets breadth and an
    honest explanation instead of an empty dashboard.
    """
    products = session.exec(
        select(Product).order_by(
            col(Product.category),
            col(Product.level),
            col(Product.price),
            col(Product.id),
        )
    ).all()

    picks: list[int] = []
    seen_categories: set[str] = set()
    for product in products:
        if product.category in seen_categories:
            continue
        seen_categories.add(product.category)
        picks.append(product.id)
        if len(picks) >= COLD_START_CATEGORIES:
            break

    logger.info(
        "agent.cold_start user_id=%s picks=%d llm_calls=0", state["user_id"], len(picks)
    )
    return {
        "message": COLD_START_MESSAGE,
        "product_ids": picks,
        "status": "ok" if picks else "degraded",
        "error": None if picks else "Catalog is empty.",
    }


@timed("plan_queries")
def plan_queries(state: AgentState) -> dict[str, Any]:
    """**MESH CALL #1** — profile into 2–3 semantic search queries.

    On failure the run does not stop: queries are derived from the profile
    deterministically and the run is marked degraded. A planner outage should
    cost query quality, not the whole recommendation.
    """
    fallback = _fallback_queries(state["profile"])

    try:
        payload = mesh_client.chat_json(
            build_query_planner_prompt(state["profile"], state["recent_signals"])
        )
    except (MeshUnavailableError, ValueError) as exc:
        logger.warning("agent.plan_queries_failed error=%s", exc)
        return {
            "queries": fallback,
            "status": "degraded",
            "error": f"Query planner unavailable: {exc}",
        }

    raw = payload.get("queries", [])
    queries = [q.strip() for q in raw if isinstance(q, str) and q.strip()][:MAX_QUERIES]

    return {
        "queries": queries or fallback,
        "llm_calls": state["llm_calls"] + 1,
    }


@timed("retrieve")
def retrieve(state: AgentState, session: Session) -> dict[str, Any]:
    """Search the active retriever. Chroma when embeddings answer, keyword otherwise."""
    retriever = get_retriever()
    candidates = retriever.search(
        session, state["queries"], top_k=settings.retrieval_top_k
    )

    logger.info(
        "agent.retrieve backend=%s queries=%d candidates=%d broadened=%s",
        retriever.name,
        len(state["queries"]),
        len(candidates),
        state["broadened"],
    )
    return {"retrieved": candidates}


@timed("filter_relevance")
def filter_relevance(state: AgentState) -> dict[str, Any]:
    """Keep candidates above the similarity threshold. Pure Python.

    On the second pass — after deterministic broadening — a thin result set
    falls back to the best few retrieved regardless of threshold. Better to
    ground the generator in the closest thing the catalog has than to hand it
    nothing and call the run degraded.
    """
    threshold = settings.retrieval_similarity_threshold
    kept = [c for c in state["retrieved"] if c["similarity"] >= threshold]

    if (
        state["broadened"]
        and len(kept) < settings.retrieval_min_candidates
        and state["retrieved"]
    ):
        kept = state["retrieved"][: settings.retrieval_min_candidates]

    return {"filtered": kept}


@timed("broaden")
def broaden(state: AgentState) -> dict[str, Any]:
    """Widen the search deterministically — no second planner call.

    Splits the existing queries into their individual terms and adds the
    profile's strongest topics as bare queries. Capped at one pass by the graph.
    """
    widened: list[str] = []
    for query in state["queries"]:
        for term in query.split():
            if len(term) > 2:
                widened.append(term)

    widened.extend(_fallback_queries(state["profile"]))

    deduped = list(dict.fromkeys(widened))[: MAX_QUERIES * 2]
    logger.info("agent.broaden from=%d to=%d", len(state["queries"]), len(deduped))
    return {"queries": deduped or state["queries"], "broadened": True}


@timed("rerank")
def rerank(state: AgentState, session: Session) -> dict[str, Any]:
    """The architecture §3.5 weighted formula. No LLM, by design.

        final = 1.00·semantic + 0.80·interest + 0.30·recency + 0.40·level
                − 0.60·negative_interest − 0.50·already_seen
    """
    profile = state["profile"]
    seen = set(state["seen_product_ids"])

    recent_categories = {
        slugify(product.category)
        for _, product in _recent_rows(session, state["user_id"], RECENCY_WINDOW_EVENTS)
        if product is not None
    }

    scored: list[dict[str, Any]] = []
    for candidate in state["filtered"]:
        category = slugify(candidate["category"])
        interest = profile.get(category, 0.0)
        level_score = profile.get(f"{LEVEL_PREFIX}{slugify(candidate['level'])}", 0.0)

        components = {
            "semantic": candidate["similarity"],
            "interest": max(interest, 0.0),
            "recency": 1.0 if category in recent_categories else 0.0,
            "level": max(level_score, 0.0),
            "negative": abs(min(interest, 0.0)),
            "seen": 1.0 if candidate["id"] in seen else 0.0,
        }
        final = (
            W_SEMANTIC * components["semantic"]
            + W_INTEREST * components["interest"]
            + W_RECENCY * components["recency"]
            + W_LEVEL * components["level"]
            - W_NEGATIVE * components["negative"]
            - W_SEEN * components["seen"]
        )
        scored.append(
            {**candidate, "score": round(final, 4), "score_components": components}
        )

    scored.sort(key=lambda c: c["score"], reverse=True)
    return {"reranked": scored[:MAX_CANDIDATES_TO_GENERATOR]}


@timed("generate")
def generate(state: AgentState) -> dict[str, Any]:
    """**MESH CALL #2** — persuasive copy plus chosen IDs, as structured JSON.

    On failure the run degrades and `store` keeps the previous recommendation
    (CONTEXT R7). No non-Mesh provider is ever consulted.
    """
    if not state["reranked"]:
        return {
            "status": "degraded",
            "error": "No candidates survived retrieval and filtering.",
        }

    try:
        payload = mesh_client.chat_json(
            build_generator_prompt(
                state["profile"], state["recent_signals"], state["reranked"]
            )
        )
    except (MeshUnavailableError, ValueError) as exc:
        logger.warning("agent.generate_failed error=%s", exc)
        return {
            "status": "degraded",
            "error": f"Generator unavailable: {exc}",
        }

    raw_ids = payload.get("products", [])
    proposed = [int(pid) for pid in raw_ids if isinstance(pid, (int, str)) and str(pid).lstrip("-").isdigit()]

    return {
        "message": str(payload.get("message", "")).strip(),
        "product_ids": proposed,
        "llm_calls": state["llm_calls"] + 1,
    }


@timed("validate")
def validate(state: AgentState) -> dict[str, Any]:
    """Drop every ID the model did not get from us. Unconditional (CONTEXT R6).

    The model cannot invent a product: anything outside the reranked candidate
    set is discarded without appeal. If fewer than two survive, the run is
    degraded and `store` keeps the previous recommendation rather than
    publishing a thin or ungrounded one.
    """
    allowed = {candidate["id"] for candidate in state["reranked"]}

    valid: list[int] = []
    for product_id in state["product_ids"]:
        if product_id in allowed and product_id not in valid:
            valid.append(product_id)

    dropped = len(state["product_ids"]) - len(valid)
    if dropped:
        logger.warning(
            "agent.validate_dropped_ids user_id=%s dropped=%d proposed=%s allowed=%s",
            state["user_id"],
            dropped,
            state["product_ids"],
            sorted(allowed),
        )

    valid = valid[:MAX_RECOMMENDED_PRODUCTS]

    if state["status"] == "degraded":
        return {"product_ids": valid}

    if len(valid) < MIN_VALID_PRODUCTS:
        return {
            "product_ids": valid,
            "status": "degraded",
            "error": (
                f"Only {len(valid)} of {len(state['product_ids'])} returned IDs were "
                "grounded in the candidate set."
            ),
        }

    if not state["message"]:
        return {
            "product_ids": valid,
            "status": "degraded",
            "error": "Generator returned no message.",
        }

    return {"product_ids": valid}


@timed("store")
def store(
    state: AgentState, session: Session, trigger_reason: str = "manual"
) -> dict[str, Any]:
    """Persist the recommendation and the run trace.

    A degraded run stores **no** recommendation: the previous one stands
    (CONTEXT R7). The `agent_runs` row is written either way — a run that
    produced nothing is exactly the run worth being able to see.
    """
    timings = state.get("node_timings", {})
    latency_ms = int(sum(timings.values()))

    trace: list[dict[str, Any]] = [
        {"node": name, "latency_ms": ms} for name, ms in timings.items()
    ]
    trace.append(
        {
            "node": "summary",
            "retrieval_backend": get_retriever().name,
            "queries": state["queries"],
            "broadened": state["broadened"],
            "funnel": {
                "retrieved": len(state["retrieved"]),
                "filtered": len(state["filtered"]),
                "reranked": len(state["reranked"]),
                "recommended": len(state["product_ids"]),
            },
            "top_candidates": [
                {
                    "id": candidate["id"],
                    "title": candidate["title"],
                    "score": candidate["score"],
                    "components": candidate["score_components"],
                }
                for candidate in state["reranked"][:5]
            ],
        }
    )

    stored = False
    if state["status"] == "ok" and state["product_ids"]:
        recommendation_service.store_recommendation(
            session,
            state["user_id"],
            message=state["message"],
            product_ids=state["product_ids"],
            interest_profile=state["profile"],
            trigger_reason=trigger_reason,
        )
        stored = True
    else:
        previous = recommendation_service.latest_recommendation(
            session, state["user_id"]
        )
        trace[-1]["retained_previous_recommendation_id"] = (
            previous.id if previous else None
        )
        logger.warning(
            "agent.degraded user_id=%s reason=%s retained_previous=%s",
            state["user_id"],
            state["error"],
            previous.id if previous else None,
        )

    session.add(
        AgentRun(
            user_id=state["user_id"],
            trigger_reason=trigger_reason,
            nodes=trace,
            llm_calls=state["llm_calls"],
            cache_hit=state["cache_hit"],
            latency_ms=latency_ms,
            status=state["status"],
            error=state["error"],
        )
    )
    session.commit()

    logger.info(
        "agent.run_complete user_id=%s status=%s llm_calls=%d stored=%s latency_ms=%d",
        state["user_id"],
        state["status"],
        state["llm_calls"],
        stored,
        latency_ms,
    )
    return {}
