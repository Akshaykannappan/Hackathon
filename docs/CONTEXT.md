# CONTEXT.md — SmartReco Core Memory

> **Read this file completely before writing any code. Re-read it before any
> architectural decision. This file is the single source of truth for this
> project. If a request contradicts this file, stop and ask.**

**Companion documents:**
- `docs/architecture.md` — how the system works end to end, in detail
- `docs/phases/phase-XX-*.md` — the scope, tasks, and exit criteria for each
  phase. Read the current phase file before starting work. Do not read ahead
  and do not build ahead.

---

## 1. What this project is

SmartReco is a course-marketplace web platform that observes user behaviour,
builds an evolving interest profile, and uses an agentic RAG pipeline to
generate personalised, persuasive, catalog-grounded course recommendations.

It is being built as a competition entry for the **SmartReco Build Challenge
2026**. The GitHub repository *is* the submission. It is screened by an
automated AI evaluator first, then by human judges.

**One-line framing:** this is not "a course website with an LLM bolted on."
It is a behavioural intelligence system that decides *what* to recommend,
*when* to recommend it, and *how* to persuade.

---

## 2. Non-negotiable rules

These are competition rules. Violating any of them invalidates the submission.

| # | Rule |
|---|------|
| R1 | **Every AI call — generative AND embeddings — must go through Mesh API.** No direct OpenAI / Anthropic / Google calls. No local embedding models (no `sentence-transformers`). |
| R2 | All AI traffic goes through exactly one module: `code/backend/app/ai/mesh_client.py`. Nothing else in the codebase may instantiate an LLM or embeddings client. |
| R3 | Backend must be Python + FastAPI. |
| R4 | No secrets committed. Ever. `.env` is gitignored. Config is read from environment only. |
| R5 | No stubbed or faked features. No hardcoded recommendations. The vector DB must be genuinely queried on every run. Dead code is scored as a failure. |
| R6 | The LLM may never invent products. It selects only from IDs supplied to it, and the backend validates every returned ID against the retrieved set. |
| R7 | On Mesh failure: retry with backoff, then serve the last stored recommendation, then log to `agent_runs`. **Never** fall back to a non-Mesh provider. |

---

## 3. Locked architecture

Do not redesign this. It was settled deliberately. Changes require explicit
discussion, not unilateral "improvement."

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Backend | FastAPI | Required by rules |
| ORM | SQLModel (SQLAlchemy core) | Typed, minimal boilerplate |
| Database | SQLite by default, via `DATABASE_URL` | Zero-setup for judges; Postgres swappable with no code change |
| Vector DB | Chroma, persistent local | No container required to evaluate |
| Embeddings | Mesh `/v1/embeddings` | Compliance (R1) |
| Agent | LangGraph | Explicit, traceable reasoning graph |
| Frontend | Jinja2 templates + vanilla JS | Required stack; no build step |
| Scheduler | APScheduler | Bonus only |
| Tracing | LangSmith | Bonus only |
| Auth | Session cookie + bcrypt | "Keep auth simple" per brief |

---

## 4. The recommendation pipeline

**Exactly two Mesh LLM calls per recommendation run.** This is a hard budget.
Adding a third requires justification against the efficiency criterion.

```
User events
    ↓
Behaviour profile builder        ← PYTHON (weighted + recency decay)
    ↓
Trigger decision                 ← PYTHON (delta threshold + cooldown + profile hash)
    ↓
Query planner                    ← MESH LLM CALL #1
    ↓
Vector retrieval (Chroma)        ← embeddings via MESH
    ↓
Relevance filtering              ← PYTHON (score threshold)
    ↓
Deterministic reranking          ← PYTHON (weighted formula)
    ↓
Recommendation generator         ← MESH LLM CALL #2 (structured JSON out)
    ↓
Product ID validation            ← PYTHON (reject anything outside retrieved set)
    ↓
Store recommendation + agent_run
```

### Behavioural scoring weights

```
search                +3.0
product_view          +2.0
time_spent > 30s      +1.5
click                 +1.0
recommendation_click  +2.0
quick_exit (<3s)      -2.0
```

Recency decay: interest weight halves every 6 hours.

### Reranking formula (no LLM)

```
final_score = semantic_similarity
            + interest_match
            + recency_signal
            + level_match
            - negative_interest
            - already_seen_penalty
```

### Trigger conditions

Generate only when **both** hold:
- accumulated interest delta since last run ≥ threshold (default 10.0)
- ≥ 10 minutes since the last generation for this user

If the profile hash is unchanged, serve the cached recommendation and make
**zero** Mesh calls.

---

## 5. Data model

| Table | Purpose |
|-------|---------|
| `users` | id, email, password_hash, role (`user` / `admin`), created_at |
| `products` | id, title, description, category, level, price, created_at, updated_at |
| `events` | id, user_id, event_type, product_id (nullable), metadata JSON, created_at |
| `recommendations` | id, user_id, message, product_ids JSON, interest_profile JSON, trigger_reason, created_at |
| `user_interest_profiles` | user_id, profile JSON, profile_hash, last_generated_at, accumulated_delta |
| `agent_runs` | id, user_id, trigger_reason, nodes JSON, llm_calls, cache_hit, latency_ms, status, error, created_at |

`agent_runs` is not optional. It powers the intelligence dashboard, which is
the primary way judges can *see* the system working.

### Dual-write invariant

Chroma document ID **is** the SQL product primary key, as a string.
Create, update, and delete must all sync. If the embedding call fails during a
write, do not half-commit — roll back the SQL write or queue the vector upsert
for retry. Sync integrity is explicitly scored.

All product mutations go through `services/product_service.py`. No route
touches Chroma or the products table directly.

---

## 6. Event tracking rules

- Client keeps an in-memory queue; flushes every 10s **or** at 20 events
- Throttle scroll; debounce search input at 500ms
- Time-on-page measured via `visibilitychange`, not a polling timer
- Flush on unload with `navigator.sendBeacon`
- `POST /api/events/batch` returns `202` immediately; trigger evaluation runs
  in a background task, never inside the request
- **Nothing in the tracking path may block or await on the UI thread**

---

## 7. Cold start

A brand-new user has no behaviour. Do not show an empty dashboard — that is a
judge's first impression.

Cold start mode: show diverse picks spanning categories, with copy along the
lines of *"SmartReco doesn't know you yet — pick a direction."* The first
interaction seeds the profile. Transition to personalised mode once the
profile crosses a minimum signal threshold.

---

## 8. Conventions

- Config via `pydantic-settings` in `app/core/config.py`. No `os.getenv` scattered around.
- All timestamps UTC, timezone-aware.
- Services hold business logic; routes stay thin.
- Type hints everywhere. Pydantic schemas for every request/response body.
- Log agent decisions in structured form, not free-text prints.
- Catalog seed target: **60–100 products across 10 distinct categories.**
  Genuinely irrelevant alternatives are what make retrieval look convincing.

---

## 9. Anti-patterns — do not do these

- Passing the whole catalog into the prompt instead of retrieving
- Recommending based on the current page rather than accumulated behaviour
- Calling Mesh on every user action
- Using an LLM for anything Python can compute deterministically
- A vector DB that is written to but never queried
- Building a heavy frontend while the AI layer stays shallow
- Adding many half-finished bonus features instead of finishing the core
- Redesigning the architecture mid-build

---

## 10. Milestones

| # | Milestone | Status |
|---|-----------|--------|
| 1 | Repo, CI green, Mesh verification script | ☐ |
| 2 | FastAPI + auth + catalog + admin CRUD | ☐ |
| 3 | SQL ↔ Chroma dual-write with sync | ☐ |
| 4 | Behavioural event tracking (batched, non-blocking) | ☐ |
| 5 | Behaviour engine + trigger engine + caching | ☐ |
| 6 | LangGraph recommendation agent | ☐ |
| 7 | Intelligence dashboard + tests + README + demo | ☐ |
| B | Bonus: LangSmith, scheduled digest, deployment | ☐ |

Each milestone has its own document under `docs/phases/`. That file defines
its scope, task list, and exit criteria — treat it as the working brief.

Milestones are sequential. Do not start milestone N+1 until N runs end to end.
Update this table as work completes.

**Documentation rule:** every `.md` file in this project lives under `docs/`.
The only exceptions are `README.md` and `CLAUDE.md`, which must stay at the
repository root.

---

## 11. Definition of done for the submission

- CI checks green on the latest commit
- README with architecture diagram, setup steps, and **measured** efficiency
  numbers (events captured vs. Mesh calls made, cache hit count, p95 tracking latency)
- Demo showing the same account's recommendations changing as behaviour changes
- Every claim in the README is true of the code
