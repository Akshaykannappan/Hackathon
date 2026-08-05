# Phase 7 — Polish, Tracing, Scheduler, Simulation & Efficiency Metrics

**Status:** ☑ Complete — All features built, verified end-to-end with measured benchmark data  
**Estimated effort:** 1 day  
**Prerequisite:** Phase 6 — Dashboard and Intelligence Panel  

> Read `docs/CONTEXT.md` and `docs/architecture.md` before starting.

---

## Goal

Finalise the production submission: implement env-gated LangSmith tracing, build the APScheduler daily digest service, create a 2-persona behavioral simulation script (`scripts/simulate_behavior.py`), benchmark system performance against competition efficiency criteria, fill `docs/efficiency_metrics.md` with empirical measurements, and update `README.md` with final architecture state.

---

## Scope

In scope:

- LangSmith tracing integration (env-gated via `LANGSMITH_TRACING` and `LANGSMITH_API_KEY`, no-op when disabled)
- APScheduler daily digest service (`app/tracking/scheduler.py`, env-gated via `ENABLE_SCHEDULER`, default OFF, runs daily at 17:00 local)
- Realistic behavior simulation script (`scripts/simulate_behavior.py`) with 2 distinct personas (Data Engineer vs Agentic AI Learner) exercising `POST /api/events/batch`
- Empirical benchmarking recording exact metrics in `docs/efficiency_metrics.md`
- Updating `README.md` to reflect implemented status, competition bonuses, and measured performance numbers

Explicitly out of scope:

- Enabling scheduler or tracing by default (must remain OFF unless explicitly enabled via environment variables)

---

## Tasks

### 7.1 LangSmith Tracing Integration

- Support `LANGSMITH_TRACING` and `LANGSMITH_API_KEY` in `app/core/config.py`.
- Wrap LangGraph graph compilation or execution with tracing hooks if enabled.
- Ensures no-op behavior when disabled or when API key is missing.

### 7.2 APScheduler Daily Digest Service (`app/tracking/scheduler.py`)

- Implement `app/tracking/scheduler.py` using `BackgroundScheduler`.
- Triggers at 17:00 local time daily.
- Finds active users from today's events, generates recommendations via `run_agent`, and sends/logs email digests.
- Gated by `settings.enable_scheduler` (default `False`). Never fires during unit tests or normal dev server boot unless enabled.

### 7.3 Behavioral Simulation Script (`scripts/simulate_behavior.py`)

- Creates two realistic user personas:
  - **Persona A (Data Engineer):** Browses data pipeline, ETL, and MLOps courses.
  - **Persona B (Agentic AI Learner):** Browses RAG, LangGraph, and Agentic AI courses.
- Sends realistic event batches through HTTP `POST /api/events/batch`.
- Demonstrates profile evolution, trigger evaluations, zero-LLM decision skips, cache hits, and recommendation generation.

### 7.4 Empirical Benchmarking (`docs/efficiency_metrics.md`)

- Perform a full simulation run via `scripts/simulate_behavior.py`.
- Record exact empirical numbers:
  - Ingest latency (p50 / p95)
  - Events captured, Mesh LLM calls, cache hits
  - LLM calls per 100 events
  - Retrieval funnel counts
  - End-to-end agent run latency
- Replace synthetic placeholders with real measured trace.

### 7.5 Final Documentation Updates (`README.md` & `CLAUDE.md`)

- Update `README.md` feature status table to Implemented.
- Add competition efficiency metrics and bonus feature disclosures to `README.md`.
- Mark Phase 7 complete in `CLAUDE.md`.

---

## Exit criteria

All must be true:

- [x] LangSmith tracing is env-gated and no-ops when disabled
- [x] `app/tracking/scheduler.py` is env-gated (default OFF) and fires at 17:00 local when enabled
- [x] `scripts/simulate_behavior.py` executes successfully against live server and generates distinct persona profiles
- [x] `docs/efficiency_metrics.md` contains 100% real measured empirical figures from simulation run
- [x] `README.md` lists all features as Implemented with measured efficiency numbers
- [x] Fresh clone boots via `python main.py` with 0 errors with default config
- [x] All unit tests pass cleanly (`pytest`)

---

## Decisions recorded in this phase

| Item | Value |
|------|-------|
| LangSmith Tracing Gating | `LANGSMITH_TRACING=true` & `LANGSMITH_API_KEY` |
| Scheduler Gating | `ENABLE_SCHEDULER=true` (default `False`) |
| Digest Time | 17:00 local time daily |
| Simulation Script | `scripts/simulate_behavior.py` |

---

## Notes / issues encountered

- **Zero-Dependency Boot:** Default `.env` leaves `LANGSMITH_TRACING=false` and `ENABLE_SCHEDULER=false`, allowing `python main.py` to start instantly without external API keys or background cron jobs interfering with tests.
