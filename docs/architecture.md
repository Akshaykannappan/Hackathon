# architecture.md — SmartReco System Architecture

> Companion to `docs/CONTEXT.md`. CONTEXT states the rules and decisions;
> this document explains how the system actually works end to end.

---

## 1. System overview

```
                            SMARTRECO

                              USER
                               │
                    ┌──────────┴──────────┐
                    │  Jinja2 templates   │
                    │  + tracker.js       │
                    └──────────┬──────────┘
                               │  batched events (10s / 20 events / sendBeacon)
                               ▼
                    POST /api/events/batch  ──► 202 Accepted (immediate)
                               │
                               │ background task
                               ▼
                    ┌──────────────────────┐
                    │   Behaviour Engine   │  PYTHON
                    │  weights + decay     │
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │   Trigger Engine     │  PYTHON
                    │ delta / cooldown /   │
                    │ profile hash         │
                    └───┬──────────────┬───┘
                        │              │
                  unchanged         changed
                        │              │
                        ▼              ▼
                 cached rec      ┌──────────────┐
                 (0 LLM calls)   │  LANGGRAPH   │
                                 │    AGENT     │
                                 └──────┬───────┘
                                        ▼
                              ┌─────────────────┐
                              │  Chroma vector  │
                              │      store      │
                              └────────┬────────┘
                                       ▼
                              stored recommendation
                                       │
                                       ▼
                              USER DASHBOARD
                              + INTELLIGENCE PANEL

        Every AI operation ───────────► mesh_client.py ───► Mesh API
```

---

## 2. Request paths

There are four distinct paths through the system. Keeping them separate is
what makes the platform fast.

| Path | Trigger | Latency budget | AI calls |
|------|---------|----------------|----------|
| Page render | user navigates | < 100ms | 0 |
| Event ingest | tracker flush | < 20ms, returns 202 | 0 |
| Recommendation generation | background, after trigger | seconds, off request path | 0 or 2 |
| Dashboard read | user opens dashboard | < 100ms | 0 |

**The critical property:** no user-facing request ever waits on an LLM.
Recommendations are generated asynchronously and *stored*. The dashboard reads
what already exists.

---

## 3. Data flow in detail

### 3.1 Tracking

`tracker.js` maintains an in-memory queue. Events are appended locally and
flushed to the backend when either condition is met:

- 10 seconds have elapsed since the last flush
- the queue reaches 20 events

Additional rules:

- scroll events are throttled
- search input is debounced at 500ms
- time-on-page is measured with `visibilitychange`, accumulating only visible
  time — not a polling timer
- on `pagehide` / unload, the queue is flushed with `navigator.sendBeacon`,
  which survives navigation
- a product view shorter than 3 seconds is emitted as `quick_exit`, a
  negative signal

The endpoint writes rows and returns `202` immediately. Trigger evaluation is
scheduled as a background task so ingest never blocks.

### 3.2 Behaviour engine

Reads the user's recent events and produces a weighted interest profile keyed
by category and extracted topic.

```
score(topic) = Σ  weight(event) × decay(age)

weight:  search +3.0 · product_view +2.0 · time>30s +1.5
         click +1.0 · recommendation_click +2.0 · quick_exit −2.0

decay:   0.5 ^ (age_hours / 6)
```

Output is a normalised dict plus a `profile_hash`:

```json
{
  "agentic_ai": 0.82,
  "langgraph": 0.71,
  "multi_agent": 0.61,
  "rag": 0.34,
  "python": 0.12,
  "web_development": -0.08
}
```

Negative values are real and used — they filter candidates during reranking.

This layer contains **no LLM calls**. It is deterministic, testable, and fast.

### 3.3 Trigger engine

Decides whether generating a new recommendation is worth an AI call.

```
accumulated_delta = Σ |new_score − old_score| across all topics

generate IF:
    accumulated_delta ≥ TRIGGER_DELTA_THRESHOLD   (default 10.0)
    AND minutes_since_last_generation ≥ 10
    AND profile_hash ≠ last_profile_hash

ELSE: serve stored recommendation, increment cache_hit, zero AI calls
```

Every decision — fire or skip — is recorded in `agent_runs` with its reason.
That table is what proves the efficiency claim in the README.

### 3.4 The agent

LangGraph with typed state. Two Mesh calls, hard budget.

```
                    START
                      │
              ┌───────▼────────┐
              │ analyze_profile│   PYTHON — load profile, recent signals,
              └───────┬────────┘            seen-product set
                      │
              ┌───────▼────────┐
              │  plan_queries  │   MESH CALL #1
              └───────┬────────┘   profile → 2-3 semantic search queries
                      │
              ┌───────▼────────┐
              │    retrieve    │   embed queries via Mesh, multi-query
              └───────┬────────┘   Chroma search, metadata filter
                      │
              ┌───────▼────────┐
              │ filter_relevance│  PYTHON — similarity threshold
              └───────┬────────┘
                      │
                 enough results?
                   ╱        ╲
                 no          yes
                 │            │
         ┌───────▼──────┐     │      broaden query deterministically,
         │   broaden    │     │      retry retrieval once — no LLM,
         └───────┬──────┘     │      loop capped at 1
                 └────────────┤
                              │
                     ┌────────▼────────┐
                     │     rerank      │  PYTHON — weighted formula
                     └────────┬────────┘
                              │
                     ┌────────▼────────┐
                     │    generate     │  MESH CALL #2 — structured JSON
                     └────────┬────────┘
                              │
                     ┌────────▼────────┐
                     │    validate     │  PYTHON — reject unknown IDs
                     └────────┬────────┘
                              │
                     ┌────────▼────────┐
                     │      store      │
                     └────────┬────────┘
                              ▼
                             END
```

Note the refinement loop uses **deterministic broadening**, not a second LLM
planning call. This preserves the two-call budget while keeping the graph
genuinely adaptive.

### 3.5 Reranking

```
final_score = 1.00 × semantic_similarity
            + 0.80 × interest_match          (profile score for its category)
            + 0.30 × recency_signal          (matches a very recent interest)
            + 0.40 × level_match             (inferred beginner/advanced fit)
            − 0.60 × negative_interest       (category with negative score)
            − 0.50 × already_seen_penalty    (viewed or previously recommended)
```

Typical funnel: 12 retrieved → 6 pass filter → 5 reranked → top 3 recommended.
Those counts are surfaced in the intelligence panel.

### 3.6 Generation and grounding

The generator prompt receives:

- the interest profile, described qualitatively (strong / medium / emerging)
- 3–5 concrete recent behavioural signals, in plain language
- the reranked candidates as a numbered list with IDs, titles, descriptions

It must return strict JSON:

```json
{
  "message": "persuasive narrative, 3-4 sentences",
  "products": [18, 32, 41],
  "reasoning": "one line on why these fit"
}
```

**Validation is unconditional.** Any ID not present in the candidate set is
dropped. If fewer than 2 valid IDs survive, the run is marked degraded and the
previous recommendation is retained. The model cannot invent a product.

---

## 4. Dual-write

```
Admin creates product
        │
        ▼
product_service.create()
        │
        ├──► SQL insert  ──────────► products table, PK = 127
        │
        └──► Mesh embed(title + description + category)
                    │
                    ▼
             Chroma upsert
             id       = "127"          ← same key, always
             document = composed text
             metadata = {category, level, price, updated_at}

        On embedding failure: roll back the SQL write.
        Never leave the two stores disagreeing.
```

Update re-embeds and upserts the same ID. Delete removes from both. Every
mutation goes through `product_service.py` — no route touches Chroma directly.

`scripts/reindex_vectors.py` rebuilds Chroma from SQL and is the recovery
path if the stores ever drift.

---

## 5. Cold start

```
new user, no events
        │
        ▼
cold_start_mode
        │
        ├── diverse picks: highest-rated product from each of N categories
        ├── copy: "SmartReco doesn't know you yet — pick a direction"
        └── zero AI calls
                │
         first interactions
                │
                ▼
        profile signal ≥ minimum threshold
                │
                ▼
        personalised mode (agent runs normally)
```

This costs almost nothing and fixes the exact moment a judge forms their first
impression.

---

## 6. Failure handling

```
Mesh request
    │
    ├─ transient error ──► tenacity backoff, 3 attempts
    │                          │
    │                     still failing
    │                          ▼
    ├─────────────────► serve last stored recommendation
    │                          │
    │                          ▼
    └─────────────────► log to agent_runs (status=degraded, error recorded)
```

Mesh performs provider-level fallback internally, so a single provider outage
is already handled inside the gateway. **The application never calls a non-Mesh
provider under any circumstance** — doing so would invalidate the submission.

---

## 7. Observability surface

`agent_runs` records, per run:

- trigger reason and the delta that caused it
- profile snapshot at generation time
- retrieval funnel counts (retrieved → filtered → reranked → recommended)
- Mesh calls made, cache hit flag
- latency per node
- status: `ok` / `degraded` / `failed`

The intelligence panel at `/intelligence` renders this live. It is the primary
mechanism by which a judge can see the system thinking rather than take the
README's word for it.

---

## 8. Module responsibilities

| Module | Owns | Must not |
|--------|------|----------|
| `ai/mesh_client.py` | all Mesh traffic, retry, typed errors | contain business logic |
| `services/vector_store.py` | Chroma read/write | be called outside product_service and the agent |
| `services/product_service.py` | dual-write integrity | be bypassed by any route |
| `services/behavior_engine.py` | profile computation | call any LLM |
| `services/trigger_engine.py` | when to generate | generate anything itself |
| `services/reranker.py` | deterministic ordering | call any LLM |
| `agent/nodes.py` | graph node logic | construct AI clients directly |
| `routes/*` | HTTP shape, auth, validation | contain business logic |

---

## 9. Configuration

All configuration flows through `app/core/config.py` (pydantic-settings),
sourced from environment. See `code/backend/.env.example` for the full set.
No `os.getenv` calls anywhere else in the codebase.

Swapping SQLite for Postgres is a `DATABASE_URL` change with no code edits.
