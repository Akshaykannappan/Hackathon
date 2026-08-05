"""The trigger engine: the three conditions, the caching path, and the audit row."""

import inspect
from datetime import timedelta

import pytest
from sqlmodel import Session, select

from app.core.config import settings
from app.models import AgentRun, Product, User, UserInterestProfile
from app.services import behavior_engine, trigger_engine
from app.services.trigger_engine import (
    REASON_BELOW_THRESHOLD,
    REASON_COOLDOWN,
    REASON_FIRE,
    REASON_NO_SIGNAL,
    REASON_PROFILE_UNCHANGED,
    should_generate,
)
from tests.conftest import NOW, add_event, seed_profile


def runs(session: Session) -> list[AgentRun]:
    return list(session.exec(select(AgentRun).order_by(AgentRun.id)).all())


def force_over_threshold(session: Session, user: User) -> None:
    """Put accumulated delta just under the threshold so one event clears it."""
    seed_profile(
        session,
        user,
        accumulated_delta=settings.trigger_delta_threshold,
    )


# ------------------------------------------------------------------ skipping


def test_no_events_means_no_signal(session: Session, user: User):
    decision = should_generate(session, user.id, now=NOW)

    assert decision.fire is False
    assert decision.reason == REASON_NO_SIGNAL
    assert decision.profile == {}


def test_small_movement_is_below_the_threshold(
    session: Session, user: User, products: dict[str, Product]
):
    """One product view is real signal, but nowhere near worth an AI call."""
    add_event(session, user, "product_view", product=products["rag"])

    decision = should_generate(session, user.id, now=NOW)

    assert decision.fire is False
    assert decision.reason == REASON_BELOW_THRESHOLD
    assert 0 < decision.accumulated_delta < settings.trigger_delta_threshold


def test_unchanged_profile_yields_a_cache_hit(
    session: Session, user: User, products: dict[str, Product]
):
    """The zero-Mesh-call path: same hash, serve what is already stored."""
    add_event(session, user, "product_view", product=products["rag"])
    first = should_generate(session, user.id, now=NOW)

    second = should_generate(session, user.id, now=NOW)

    assert first.cache_hit is False  # nothing stored to hit on the first pass
    assert second.cache_hit is True
    assert second.fire is False
    assert second.reason == REASON_PROFILE_UNCHANGED
    assert second.profile_hash == first.profile_hash


def test_cache_hit_is_recorded_on_the_run(
    session: Session, user: User, products: dict[str, Product]
):
    add_event(session, user, "product_view", product=products["rag"])
    should_generate(session, user.id, now=NOW)
    should_generate(session, user.id, now=NOW)

    assert [run.cache_hit for run in runs(session)] == [False, True]


def test_empty_profile_is_not_a_cache_hit(session: Session, user: User):
    """There is no previous recommendation to serve, so nothing was hit."""
    should_generate(session, user.id, now=NOW)
    decision = should_generate(session, user.id, now=NOW)

    assert decision.cache_hit is False
    assert decision.reason == REASON_NO_SIGNAL


# -------------------------------------------------------------------- firing


def test_fires_when_all_three_conditions_hold(
    session: Session, user: User, products: dict[str, Product]
):
    add_event(session, user, "product_view", product=products["rag"])
    force_over_threshold(session, user)

    decision = should_generate(session, user.id, now=NOW)

    assert decision.fire is True
    assert decision.reason == REASON_FIRE
    assert decision.accumulated_delta >= settings.trigger_delta_threshold
    assert decision.cache_hit is False


def test_firing_resets_the_accumulator_and_stamps_the_generation(
    session: Session, user: User, products: dict[str, Product]
):
    add_event(session, user, "product_view", product=products["rag"])
    force_over_threshold(session, user)

    should_generate(session, user.id, now=NOW)

    stored = session.get(UserInterestProfile, user.id)
    assert stored.accumulated_delta == 0.0
    assert stored.last_generated_at == NOW


def test_cooldown_blocks_a_second_fire_inside_ten_minutes(
    session: Session, user: User, products: dict[str, Product]
):
    """The headline guard: two qualifying bursts, one generation."""
    add_event(session, user, "product_view", product=products["rag"])
    force_over_threshold(session, user)
    first = should_generate(session, user.id, now=NOW)

    # New behaviour, and enough accumulated change to qualify again.
    add_event(session, user, "product_view", product=products["agentic"])
    force_over_threshold(session, user)

    inside_cooldown = NOW + timedelta(
        minutes=settings.trigger_cooldown_minutes - 1
    )
    second = should_generate(session, user.id, now=inside_cooldown)

    assert first.fire is True
    assert second.fire is False
    assert second.reason == REASON_COOLDOWN


def test_fires_again_once_the_cooldown_has_passed(
    session: Session, user: User, products: dict[str, Product]
):
    add_event(session, user, "product_view", product=products["rag"])
    force_over_threshold(session, user)
    should_generate(session, user.id, now=NOW)

    add_event(session, user, "product_view", product=products["agentic"])
    force_over_threshold(session, user)

    after_cooldown = NOW + timedelta(
        minutes=settings.trigger_cooldown_minutes, seconds=1
    )
    decision = should_generate(session, user.id, now=after_cooldown)

    assert decision.fire is True
    assert decision.reason == REASON_FIRE


def test_cooldown_does_not_apply_before_the_first_generation(
    session: Session, user: User, products: dict[str, Product]
):
    """A brand-new user is not in cooldown for a recommendation they never had."""
    add_event(session, user, "product_view", product=products["rag"])
    force_over_threshold(session, user)

    assert should_generate(session, user.id, now=NOW).fire is True


# --------------------------------------------------------------- accumulation


def test_delta_carries_forward_across_skips(
    session: Session, user: User, products: dict[str, Product]
):
    """Change accumulates over evaluations until it is worth spending on.

    A single click (+1.0) builds a profile with delta < TRIGGER_DELTA_THRESHOLD.
    A second click on a different category adds more change, and at that point
    the accumulated delta clears the threshold.  The key invariant is that the
    second evaluation's accumulated_delta is strictly larger than the first's.
    """
    # First event: click on rag — small delta (interest score contribution < threshold)
    add_event(session, user, "click", product=products["rag"])
    first = should_generate(session, user.id, now=NOW)

    # The delta from one click alone must be strictly below the threshold.
    assert first.accumulated_delta < settings.trigger_delta_threshold
    assert first.fire is False

    # Second event: click on a different category — delta grows.
    add_event(session, user, "click", product=products["design"])
    second = should_generate(session, user.id, now=NOW)

    # Accumulated delta must have grown across evaluations.
    assert second.accumulated_delta > first.accumulated_delta


def test_skipping_leaves_the_generation_stamp_untouched(
    session: Session, user: User, products: dict[str, Product]
):
    seed_profile(session, user, last_generated_at=NOW - timedelta(hours=3))
    add_event(session, user, "product_view", product=products["rag"])

    should_generate(session, user.id, now=NOW)

    stored = session.get(UserInterestProfile, user.id)
    assert stored.last_generated_at == NOW - timedelta(hours=3)


# ------------------------------------------------------------- persistence


def test_profile_is_persisted_on_every_evaluation(
    session: Session, user: User, products: dict[str, Product]
):
    add_event(session, user, "product_view", product=products["rag"])

    decision = should_generate(session, user.id, now=NOW)

    stored = session.get(UserInterestProfile, user.id)
    assert stored is not None
    assert stored.profile == decision.profile
    assert stored.profile_hash == decision.profile_hash


def test_every_decision_writes_exactly_one_agent_run(
    session: Session, user: User, products: dict[str, Product]
):
    """Skips are the efficiency evidence, so they are recorded like anything else."""
    add_event(session, user, "product_view", product=products["rag"])

    should_generate(session, user.id, now=NOW)
    should_generate(session, user.id, now=NOW)
    should_generate(session, user.id, now=NOW)

    assert len(runs(session)) == 3


def test_agent_run_records_the_reason_and_costs_no_llm_call(
    session: Session, user: User, products: dict[str, Product]
):
    add_event(session, user, "product_view", product=products["rag"])

    decision = should_generate(session, user.id, now=NOW)

    run = runs(session)[-1]
    assert run.trigger_reason == decision.reason
    assert run.llm_calls == 0
    assert run.status == "ok"
    assert run.error is None


def test_agent_run_carries_a_readable_trace(
    session: Session, user: User, products: dict[str, Product]
):
    """The dashboard renders these nodes, so they must hold real numbers."""
    add_event(session, user, "product_view", product=products["rag"])
    add_event(session, user, "search", metadata={"query": "vector database"})

    should_generate(session, user.id, now=NOW)

    node = runs(session)[-1].nodes[0]
    assert node["node"] == "trigger_evaluation"
    assert node["events_considered"] == 2
    assert node["topics"] > 0
    assert node["top_topics"][0]["topic"]


# --------------------------------------------------------------- compliance


@pytest.mark.parametrize("module", [behavior_engine, trigger_engine])
def test_module_makes_no_ai_calls(module):
    """CONTEXT R2 and §9: this layer is deterministic Python, permanently."""
    source = inspect.getsource(module)

    assert "mesh_client" not in source
    assert "openai" not in source
