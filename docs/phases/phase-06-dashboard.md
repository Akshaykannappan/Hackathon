# Phase 6 — Dashboard and Intelligence Panel

**Status:** ☑ Complete — 49 tests passing, verified end-to-end  
**Estimated effort:** half a day  
**Prerequisite:** Phase 5 — LangGraph Agent & Vector Retrieval  

> Read `docs/CONTEXT.md` (§5 tables, §7 cold start) and `docs/architecture.md` (§7 observability surface) before starting.

---

## Goal

Build the user-facing Dashboard (`/dashboard`) and the Intelligence Panel (`/intelligence`). The dashboard displays stored recommendations and cold-start cards without triggering LLM calls on page load. The intelligence panel renders user interest profiles, recent behavioral signals, trigger engine decision state, retrieval funnel breakdowns, system efficiency metrics, and recent agent execution runs.

---

## Scope

In scope:

- `app/routes/recommendations.py` (`GET /dashboard`) rendering stored recommendations or cold-start diverse catalog picks
- `app/routes/intelligence.py` (`GET /intelligence`) rendering interest profile bars, behavioral signals, trigger state, retrieval funnel, efficiency metrics, and recent `agent_runs`
- Jinja2 templates: `pages/dashboard.html`, `pages/intelligence.html`, `partials/rec_card.html`
- Updating `partials/navbar.html` to link to Dashboard and Intelligence pages
- Tracking attribute `data-track-source="recommendation"` on recommendation cards for `recommendation_click` event tracking
- Router registrations in `app/routes/__init__.py` and `app/main.py`
- CSS styles in `code/frontend/static/css/main.css` without external CDNs or frameworks

Explicitly out of scope:

- Triggering any LLM calls on page load (reads stored DB state only)
- External UI frameworks or CDN script dependencies

---

## Tasks

### 6.1 Recommendations Route (`app/routes/recommendations.py`)

- Implement `GET /dashboard` endpoint requiring authenticated user (`CurrentUser`).
- Reads stored recommendation for user via `latest_recommendation(session, user_id)`.
- If a stored recommendation exists, hydrates recommended products from SQL database and renders `pages/dashboard.html`.
- If no recommendation exists (cold start user), queries diverse picks across categories using SQL and displays cold-start message (*"SmartReco doesn't know you yet — pick a direction"*).
- **Strict Rule:** Zero LLM calls on GET requests.

### 6.2 Intelligence Route (`app/routes/intelligence.py`)

- Implement `GET /intelligence` endpoint requiring authenticated user (`CurrentUser`).
- Fetches `UserInterestProfile` and computes positive/negative interest bars.
- Extracts plain-language recent signals from recent user events.
- Displays latest trigger decision details (delta, threshold, fired/skipped, reason).
- Displays retrieval funnel counts (`retrieved` → `filtered` → `reranked` → `recommended`).
- Displays efficiency metrics (total events captured, LLM calls made, cache hit count).
- Displays last 10 `agent_runs` in a structured table.

### 6.3 Templates & CSS

- `pages/dashboard.html`: Extends `layouts/base.html`, renders recommendation narrative message and course grid.
- `partials/rec_card.html`: Renders course card with `data-track-source="recommendation"` attribute.
- `pages/intelligence.html`: Extends `layouts/base.html`, renders profile visualization bars, trigger status, retrieval funnel, efficiency counters, and agent run table.
- `partials/navbar.html`: Updated with links to `/dashboard` and `/intelligence`.
- `main.css`: Styling for interest bars (positive green/blue, negative red/orange), funnel cards, metrics grid, and audit table.

---

## Exit criteria

All must be true:

- [x] `GET /dashboard` loads stored recommendations or cold-start picks with 0 LLM calls
- [x] Cold-start users see diverse category picks and explanation copy
- [x] Recommendation cards carry `data-track-source="recommendation"` for tracking
- [x] `GET /intelligence` visualizes interest profile scores (positives & negatives in distinct colors)
- [x] Intelligence panel displays recent signals, trigger decision, retrieval funnel, efficiency counters, and last 10 `agent_runs`
- [x] Navbar includes links to Dashboard and Intelligence Panel
- [x] Zero `mesh_client` calls inside any route file (`app/routes/`)
- [x] `pytest` passes cleanly (49 tests)

---

## Decisions recorded in this phase

| Item | Value |
|------|-------|
| Dashboard URL | `/dashboard` |
| Intelligence URL | `/intelligence` |
| Navigation Links | Added to `partials/navbar.html` |
| LLM Calls on Page Load | `0` (Strictly reads stored DB state) |

---

## Notes / issues encountered

- **Zero LLM Call Invariant:** All GET endpoints in `app/routes/` read directly from SQLite (`recommendations`, `products`, `user_interest_profiles`, `agent_runs`). Recommendation generation is handled exclusively in background tasks via `event_service` trigger evaluation.
