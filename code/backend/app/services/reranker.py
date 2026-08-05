"""Deterministic candidate reranking based on user profile and context (CONTEXT §3.5).

Pure Python, zero LLM calls.

Reranking formula:
    final_score = 1.00 * semantic_similarity
                + 0.80 * interest_match
                + 0.30 * recency_signal
                + 0.40 * level_match
                - 0.60 * negative_interest
                - 0.50 * already_seen_penalty
"""

from typing import Any

from app.services.behavior_engine import LEVEL_PREFIX, slugify


def rerank_candidates(
    candidates: list[dict[str, Any]],
    profile: dict[str, float],
    recent_signals: list[str] | None = None,
    seen_product_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Rerank candidate courses deterministically using weighted scoring."""
    if not candidates:
        return []

    signals = [s.lower() for s in (recent_signals or [])]
    seen_ids = set(seen_product_ids or [])

    reranked = []
    for candidate in candidates:
        category_slug = slugify(candidate.get("category", ""))
        level_slug = f"{LEVEL_PREFIX}{slugify(candidate.get('level', ''))}"

        # 1. Similarity (0.0 to 1.0)
        similarity = float(candidate.get("similarity", 0.0))

        # 2. Interest match (category profile score, if positive)
        cat_score = profile.get(category_slug, 0.0)
        interest_match = max(0.0, cat_score)
        negative_interest = abs(cat_score) if cat_score < 0 else 0.0

        # 3. Recency signal (matches recent actions)
        title_lower = candidate.get("title", "").lower()
        recency_signal = 1.0 if any(sig in title_lower or sig in category_slug for sig in signals) else 0.0

        # 4. Level match (level profile score, if positive)
        level_score = profile.get(level_slug, 0.0)
        level_match = max(0.0, level_score)

        # 5. Already seen penalty
        already_seen_penalty = 1.0 if candidate.get("id") in seen_ids else 0.0

        final_score = (
            1.00 * similarity
            + 0.80 * interest_match
            + 0.30 * recency_signal
            + 0.40 * level_match
            - 0.60 * negative_interest
            - 0.50 * already_seen_penalty
        )

        item = dict(candidate)
        item["rerank_score"] = round(final_score, 4)
        reranked.append(item)

    reranked.sort(key=lambda x: x["rerank_score"], reverse=True)
    return reranked
