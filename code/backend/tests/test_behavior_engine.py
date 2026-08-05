"""The behaviour engine: weights, decay, normalisation, hashing."""

import pytest
from sqlmodel import Session

from app.models import Product, User
from app.services.behavior_engine import (
    HALF_LIFE_HOURS,
    LEVEL_CAP,
    LEVEL_PREFIX,
    build_profile,
    compute_profile_hash,
    profile_delta,
)
from tests.conftest import NOW, add_event


def profile_for(session: Session, user: User) -> dict[str, float]:
    return build_profile(session, user.id, now=NOW).profile


# --------------------------------------------------------------------- decay


def test_decay_halves_signal_every_half_life(
    session: Session, user: User, products: dict[str, Product]
):
    """An event one half-life (0.75h) old is worth exactly half a fresh one."""
    add_event(session, user, "product_view", product=products["rag"])
    add_event(
        session,
        user,
        "product_view",
        product=products["agentic"],
        hours_ago=HALF_LIFE_HOURS,
    )

    profile = profile_for(session, user)

    assert profile["rag"] == pytest.approx(1.0)
    assert profile["agentic_ai"] == pytest.approx(0.5)


def test_decay_keeps_shrinking_over_successive_half_lives(
    session: Session, user: User, products: dict[str, Product]
):
    add_event(session, user, "product_view", product=products["rag"])
    add_event(
        session,
        user,
        "product_view",
        product=products["agentic"],
        hours_ago=HALF_LIFE_HOURS * 3,
    )

    profile = profile_for(session, user)

    assert profile["agentic_ai"] == pytest.approx(0.125)


def test_old_signal_ranks_below_recent_signal(
    session: Session, user: User, products: dict[str, Product]
):
    """An older strong interest loses to today's weaker fresh interest."""
    # A search is worth +3.0, a click only +1.0 — but 4 half-lives (3 hours)
    # leaves the search with 3.0 * 0.0625 = 0.1875.
    add_event(
        session, user, "search", metadata={"query": "kubernetes"}, hours_ago=HALF_LIFE_HOURS * 4
    )
    add_event(session, user, "click", product=products["rag"])

    profile = profile_for(session, user)

    assert profile["rag"] > profile["kubernetes"]


# ------------------------------------------------------------------- weights


def test_weights_follow_context_table(
    session: Session, user: User, products: dict[str, Product]
):
    """product_view (+2.0) against click (+1.0), both fresh."""
    add_event(session, user, "product_view", product=products["rag"])
    add_event(session, user, "click", product=products["agentic"])

    profile = profile_for(session, user)

    assert profile["rag"] == pytest.approx(1.0)
    assert profile["agentic_ai"] == pytest.approx(0.5)


def test_quick_exit_produces_a_negative_score(
    session: Session, user: User, products: dict[str, Product]
):
    """A bounce is a negative signal, not the absence of a positive one."""
    add_event(session, user, "quick_exit", product=products["design"])

    profile = profile_for(session, user)

    assert profile["design"] < 0
    assert profile[f"{LEVEL_PREFIX}beginner"] < 0


def test_quick_exit_cancels_an_earlier_view(
    session: Session, user: User, products: dict[str, Product]
):
    """Viewing (+2.0) then bouncing (−2.0) nets out to no interest at all."""
    add_event(session, user, "product_view", product=products["design"])
    add_event(session, user, "quick_exit", product=products["design"])

    profile = profile_for(session, user)

    assert "design" not in profile


def test_negative_and_positive_topics_coexist(
    session: Session, user: User, products: dict[str, Product]
):
    add_event(session, user, "product_view", product=products["rag"])
    add_event(session, user, "quick_exit", product=products["design"])

    profile = profile_for(session, user)

    assert profile["rag"] > 0
    assert profile["design"] < 0


def test_time_spent_below_threshold_carries_no_weight(
    session: Session, user: User, products: dict[str, Product]
):
    """CONTEXT §4 weights `time_spent > 30s`, so 12 seconds scores nothing."""
    add_event(
        session,
        user,
        "time_spent",
        product=products["rag"],
        metadata={"seconds": 12},
    )

    assert profile_for(session, user) == {}


def test_time_spent_above_threshold_counts(
    session: Session, user: User, products: dict[str, Product]
):
    add_event(
        session,
        user,
        "time_spent",
        product=products["rag"],
        metadata={"seconds": 45},
    )

    assert profile_for(session, user)["rag"] == pytest.approx(1.0)


def test_unweighted_event_types_score_nothing(
    session: Session, user: User, products: dict[str, Product]
):
    """`category_view` and `scroll_depth` are captured but unweighted."""
    add_event(session, user, "category_view", metadata={"category": "RAG"})
    add_event(
        session, user, "scroll_depth", product=products["rag"], metadata={"depth": 50}
    )

    snapshot = build_profile(session, user.id, now=NOW)

    assert snapshot.profile == {}
    assert snapshot.event_count == 2  # captured, just not scored


# -------------------------------------------------------------------- topics


def test_product_events_record_category_and_level(
    session: Session, user: User, products: dict[str, Product]
):
    add_event(session, user, "product_view", product=products["agentic"])

    profile = profile_for(session, user)

    # Category topic is at max (1.0).
    assert profile["agentic_ai"] == pytest.approx(1.0)
    # Level topic must be capped at LEVEL_CAP × top-category (= 0.5).
    assert profile[f"{LEVEL_PREFIX}advanced"] == pytest.approx(LEVEL_CAP)
    # Level always strictly below any category topic.
    assert profile[f"{LEVEL_PREFIX}advanced"] < profile["agentic_ai"]


def test_search_splits_its_weight_across_topics(session: Session, user: User):
    """A three-word query is still worth one search, not three."""
    add_event(session, user, "search", metadata={"query": "vector database"})

    profile = profile_for(session, user)

    # Two tokens plus the joined phrase, each carrying a third of +3.0.
    assert set(profile) == {"vector", "database", "vector_database"}
    assert all(score == pytest.approx(1.0) for score in profile.values())


def test_search_phrase_matches_a_multi_word_category(
    session: Session, user: User, products: dict[str, Product]
):
    """Searching "agentic ai" reinforces the "Agentic AI" category topic."""
    add_event(session, user, "search", metadata={"query": "agentic ai"})
    add_event(session, user, "product_view", product=products["agentic"])

    profile = profile_for(session, user)

    assert profile["agentic_ai"] == max(profile.values())


def test_search_ignores_stopwords_and_short_tokens(session: Session, user: User):
    add_event(session, user, "search", metadata={"query": "how to learn rag"})

    assert set(profile_for(session, user)) == {"rag"}


def test_event_for_deleted_product_is_skipped(session: Session, user: User):
    """No product row means nothing to attribute the weight to."""
    add_event(session, user, "product_view")

    assert profile_for(session, user) == {}


# ------------------------------------------------------------- normalisation


def test_scores_are_normalised_into_unit_range(
    session: Session, user: User, products: dict[str, Product]
):
    for _ in range(20):
        add_event(session, user, "product_view", product=products["rag"])
    add_event(session, user, "quick_exit", product=products["design"])

    profile = profile_for(session, user)

    assert max(profile.values()) == pytest.approx(1.0)
    assert all(-1.0 <= score <= 1.0 for score in profile.values())


def test_level_topics_and_category_topics_normalise_independently(
    session: Session, user: User, products: dict[str, Product]
):
    """Level topics are capped at LEVEL_CAP × top-category so they always sort below categories."""
    # rag (category) + level:advanced (+2.0 each)
    add_event(session, user, "product_view", product=products["rag"])
    # agentic (category) + level:advanced (+2.0 each)
    add_event(session, user, "product_view", product=products["agentic"])

    profile = profile_for(session, user)

    # Both categories are at max (2.0 raw → 1.0 normalised)
    assert profile["rag"] == pytest.approx(1.0)
    assert profile["agentic_ai"] == pytest.approx(1.0)
    # Level:advanced is capped at LEVEL_CAP × top_cat (1.0), not 1.0.
    assert profile[f"{LEVEL_PREFIX}advanced"] == pytest.approx(LEVEL_CAP)
    # Level never ties or exceeds a category topic.
    assert profile[f"{LEVEL_PREFIX}advanced"] < profile["rag"]
    assert profile[f"{LEVEL_PREFIX}advanced"] < profile["agentic_ai"]


def test_empty_history_yields_an_empty_profile(session: Session, user: User):
    snapshot = build_profile(session, user.id, now=NOW)

    assert snapshot.profile == {}
    assert snapshot.is_empty
    assert snapshot.event_count == 0


def test_events_are_scoped_to_one_user(
    session: Session, user: User, products: dict[str, Product]
):
    other = User(email="someone.else@example.com", password_hash="x")
    session.add(other)
    session.commit()
    session.refresh(other)

    add_event(session, other, "product_view", product=products["rag"])

    assert profile_for(session, user) == {}
    assert build_profile(session, other.id, now=NOW).profile != {}


# --------------------------------------------------------------------- hash


def test_identical_profiles_hash_identically(
    session: Session, user: User, products: dict[str, Product]
):
    """The cache check depends on this holding across runs and processes."""
    add_event(session, user, "product_view", product=products["rag"])
    add_event(session, user, "click", product=products["agentic"])

    first = build_profile(session, user.id, now=NOW)
    second = build_profile(session, user.id, now=NOW)

    assert first.profile == second.profile
    assert first.profile_hash == second.profile_hash


def test_hash_ignores_key_insertion_order():
    forwards = {"rag": 0.9, "agentic_ai": 0.4}
    backwards = {"agentic_ai": 0.4, "rag": 0.9}

    assert compute_profile_hash(forwards) == compute_profile_hash(backwards)


def test_hash_changes_when_interests_change(
    session: Session, user: User, products: dict[str, Product]
):
    add_event(session, user, "product_view", product=products["rag"])
    before = build_profile(session, user.id, now=NOW).profile_hash

    add_event(session, user, "product_view", product=products["design"])
    after = build_profile(session, user.id, now=NOW).profile_hash

    assert before != after


def test_hash_survives_floating_point_noise():
    """Rounding is what stops 0.1+0.2 from invalidating a valid cache entry."""
    assert compute_profile_hash({"rag": 0.30000000000000004}) == compute_profile_hash(
        {"rag": 0.3}
    )


def test_hash_is_a_sha256_hex_digest_fitting_the_column():
    digest = compute_profile_hash({"rag": 1.0})

    assert len(digest) == 64  # user_interest_profiles.profile_hash is VARCHAR(64)


# -------------------------------------------------------------------- deltas


def test_delta_of_identical_profiles_is_zero():
    profile = {"rag": 0.9, "agentic_ai": 0.4}

    assert profile_delta(profile, dict(profile)) == 0.0


def test_delta_counts_a_brand_new_topic_in_full():
    assert profile_delta({}, {"rag": 0.75}) == pytest.approx(0.75)
    assert profile_delta(None, {"rag": 0.75}) == pytest.approx(0.75)


def test_delta_counts_a_dropped_topic():
    assert profile_delta({"rag": 0.5}, {}) == pytest.approx(0.5)


def test_delta_sums_absolute_movement_across_topics():
    old = {"rag": 0.5, "design": -0.2}
    new = {"rag": 0.9, "design": -0.4}

    assert profile_delta(old, new) == pytest.approx(0.6)
