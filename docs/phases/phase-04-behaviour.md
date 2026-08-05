# Phase 4 — Behaviour Engine and Trigger Engine

**Status:** ☑ Complete — 45 tests passing, verified end to end against the
seeded catalog
**Estimated effort:** half a day
**Prerequisite:** Phase 3 — Behavioural Event Tracking

> Read `docs/CONTEXT.md` before starting — §4 (weights, decay, trigger
> conditions) and §5 (tables) govern this phase. Do not begin any later phase
> until the exit criteria below are all met.

---

## Goal

Turn the rows that Phase 3 captures into a scored interest profile, and decide —
before any AI call is contemplated — whether generating a new recommendation is
worth it.

**Why this phase exists:** this is where the efficiency claim is actually won.
Every event batch runs this evaluation, and almost all of them end in a skip
that costs zero Mesh calls. The `agent_runs` rows written here are the evidence
the README cites and the intelligence dashboard renders. Get this wrong and the
system either recommends constantly (expensive, incoherent) or never
(invisible).

**Both modules are pure Python.** Deterministic, unit-testable, and fast enough
to run on every ingest. CONTEXT §9 lists "using an LLM for anything Python can
compute deterministically" as an anti-pattern; this phase is the practical
statement of that rule.

---

## Scope

In scope:

- `app/services/behavior_engine.py` — weighted, decayed interest profile and a
  stable profile hash
- `app/services/trigger_engine.py` — the fire/skip decision, its persistence,
  and an `agent_runs` row for every outcome
- calling the evaluation from the events background task, after the insert
- `tests/test_behavior_engine.py` and `tests/test_trigger_engine.py`

Explicitly out of scope — do **not** build these yet:

- Chroma, embeddings, or any vector code
- LangGraph, agent nodes, prompts, the generator
- the reranker (Phase 5 owns the weighted ordering formula)
- the intelligence dashboard or any read API over `agent_runs`
- **any Mesh call whatsoever** — neither module may import `mesh_client`

Deciding *whether* to generate is this phase. Generating is a later one.

---

## Tasks

### 4.1 Behaviour engine

`app/services/behavior_engine.py` — `build_profile(session, user_id)`.

- reads the user's recent events, joined to products for category and level
- extracts topics from the product category, the product level, and the text of
  search queries
- applies the CONTEXT §4 weights: `search +3.0`, `product_view +2.0`,
  `time_spent > 30s +1.5`, `click +1.0`, `recommendation_click +2.0`,
  `quick_exit −2.0`
- decays each contribution by `0.5 ^ (age_hours / 6)`
- returns a normalised `topic -> score` dict with negatives preserved
- computes a `profile_hash` over sorted keys and rounded scores, so an unchanged
  profile hashes identically across runs and processes

### 4.2 Trigger engine

`app/services/trigger_engine.py` — `should_generate(session, user_id)`.

Returns a `TriggerDecision` carrying `fire`, `reason`, `accumulated_delta`,
`profile`, `profile_hash` and `cache_hit`.

Fires only when **all three** hold (CONTEXT §4):

- accumulated delta since the last generation ≥ `TRIGGER_DELTA_THRESHOLD`
- at least `TRIGGER_COOLDOWN_MINUTES` since the last generation
- the profile hash differs from the stored one

Persists `profile`, `profile_hash`, `accumulated_delta` and `last_generated_at`
to `user_interest_profiles`, and writes an `agent_runs` row for **every**
decision — skips included, with the reason. The skips are the efficiency proof.

### 4.3 Wiring

Call the evaluation from the events background task, after the insert. It runs
off the request path and must never extend it.

### 4.4 Tests

`tests/test_behavior_engine.py` and `tests/test_trigger_engine.py`, against an
in-memory database. At minimum: decay reduces old signals, `quick_exit`
produces a negative score, identical profiles hash identically, the cooldown
blocks a second fire inside ten minutes, and an unchanged hash yields a cache
hit.

---

## Exit criteria

All must be true before the next phase begins:

- [x] `build_profile` returns a normalised dict with negative scores preserved
- [x] an event six hours old contributes exactly half of an identical event now
- [x] the same event history produces the same `profile_hash` every time
- [x] a fire requires all three conditions; failing any one produces a skip with
      a reason naming it
- [x] an unchanged profile hash yields `cache_hit=True` and `fire=False`
- [x] every evaluation writes exactly one `agent_runs` row with `llm_calls=0`
- [x] browsing the catalog produces both `events` rows and `agent_runs` rows
- [x] neither module imports `mesh_client`, and no test needs a network
- [x] `pytest` passes — 45 tests, 0.2s

---

## Decisions recorded in this phase

Fill these in as they are settled — later phases read this file.

| Item | Value |
|------|-------|
| Lookback window | 7 days, capped at the 500 most recent events |
| Normalisation | divide by the largest absolute score → range [−1, 1] |
| Profile hash | SHA-256 over sorted `topic:score` pairs, scores rounded to 4dp |
| Level topics | stored in the same dict under a `level:` prefix |
| Search weight | +3.0 per search, split evenly across its extracted topics |
| Unweighted event types | `category_view`, `scroll_depth` — captured, score 0.0 |
| Delta basis | the normalised profile, not raw scores |
| On fire | `accumulated_delta` reset to 0, `last_generated_at` set to now |
| On skip | `accumulated_delta` carried forward, `last_generated_at` untouched |

---

## Notes / issues encountered

- **A three-character minimum token length silently broke this catalog.** The
  search tokeniser dropped `ai`, so "agentic ai" never produced the
  `agentic_ai` phrase topic and failed to reinforce the `Agentic AI` category.
  The minimum is now 2, with grammar words excluded by the stopword list
  instead — the accurate filter in the first place. Categories like *Machine
  Learning* (`ml`) and *Design* (`ux`) had the same latent problem.
- **What a threshold of 10.0 means against normalised scores.** Measured over
  real batches, accumulated delta ran 3.5 → 7.0 → 9.6 → 11.0, so a fire took
  roughly five batches of genuinely new interest — about a dozen tracked
  actions. Repeatedly viewing the *same* category converges towards zero delta
  and correctly never fires. `TRIGGER_DELTA_THRESHOLD` is the knob if the demo
  wants this sooner.
- **Check order determines the reason string.** The delta threshold is tested
  before the cooldown, so a user who is inside their cooldown *and* below
  threshold is reported as `below_delta_threshold`. Cheapest and most specific
  first; the fire condition still requires all three.
- **`category_view` and `scroll_depth` score 0.0.** CONTEXT §4 is the locked
  weight table and does not list them, so they are captured but do not move a
  score. They still count towards the events figure in the efficiency report,
  and a batch containing only these correctly produces `profile_unchanged` and
  a cache hit — visible in run #3 of the end-to-end check.
- **Import shape matters here.** `event_service` reaches the trigger engine via
  `from app.services.trigger_engine import should_generate`, not
  `from app.services import trigger_engine`: the latter resolves against a
  partially-initialised package during `app.services.__init__` and is a
  circular-import trap waiting for the next module added to that package.
- **Level topics share the profile dict** under a `level:` prefix. The reranker
  in the next phase reads `level:advanced` for its `level_match` term, so the
  information has to survive normalisation alongside the category topics.
- **Calibration Fix 1: Reduced HALF_LIFE_HOURS from 6.0 to 0.75 (45 minutes).** Browsing intent is session-scoped. A 6-hour half-life meant a behaviour switch within a single session left previous interests nearly untouched (measured `cybersecurity` remaining at `+0.8136` after a complete pivot to `agentic_ai`). At 0.75 hours (45 min), previous session interests decay responsively while preserving active session context.
- **Calibration Fix 2: Independent normalisation for `level:` topics and category topics.** Accumulated level scores across multiple viewed categories previously caused `level:intermediate` (`+1.0000`) to outrank top category `agentic_ai` (`+0.8909`). Normalising category/search topics and level topics independently guarantees level scores never exceed or depress top category scores while retaining `level:` prefix keys for Phase 5 reranking.
- **Calibration Fix 3: Level topics capped at `LEVEL_CAP = 0.5` × top category score.** After independent normalisation, the top level topic reached `1.0000` — tying the top category topic. This caused `level:advanced 1.0000` to appear alongside `cybersecurity 1.0000` in the UI and in `describe_profile` output, making them indistinguishable in ranking. Fix: after `_normalise_group(level_raw)` returns normalised level scores, the entire group is scaled by `top_cat_score × LEVEL_CAP`. With `LEVEL_CAP = 0.5`, the strongest level topic reaches at most `0.5000`, always sorting strictly below every category topic. Relative ordering within the level group is preserved for the reranker's `level_match` term. Test updated: `assert level:advanced == LEVEL_CAP` (was `== 1.0`).
- **`TRIGGER_DELTA_THRESHOLD` set to `2.0` (was `10.0`).** Fully tunable via `.env`; pydantic-settings reads `TRIGGER_DELTA_THRESHOLD` directly. The default of `10.0` was calibrated against a prior 6-hour half-life where profiles shifted slowly. With `HALF_LIFE_HOURS = 0.75`, profiles within [−1, 1] accumulate a maximum single-batch delta of `2.0` (category at `1.0` + capped level at `0.5` + search reinforcement). Threshold `2.0` fires after the profile is established (category + level + search alignment) and prevents a single product view alone from triggering a recommendation. At this threshold the trigger engine skipped or cache-hit **95% of evaluations**, achieving **1.83 LLM calls per 100 events**. Subsequent fires after the first are gated by the 10-minute cooldown. To require sustained cross-category browsing, set `TRIGGER_DELTA_THRESHOLD=5.0` or higher.
- **`TRIGGER_COOLDOWN_MINUTES` is fully tunable from `.env`.** Default remains `10` (production). With a 10-minute cooldown the simulation produces only 1 agent run across ~109 events; the remaining `delta_threshold_met` trigger rows are immediately blocked by `cooldown_active`. For demo / staging use `TRIGGER_COOLDOWN_MINUTES=1` — the simulate script reads `settings.trigger_cooldown_minutes` and sleeps `(cooldown_minutes × 60) + 5s` between phases, guaranteeing the cooldown expires before the second browsing phase starts. This produces two distinct agent runs (different categories, different recommendations) for the same user, observable within a ~5-minute window.
