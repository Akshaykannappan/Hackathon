# Phase 3 — Behavioural Event Tracking

**Status:** ☑ Built — every exit criterion verified except the in-browser
`sendBeacon` check, which needs a human with a tab to close
**Estimated effort:** half a day
**Prerequisite:** Phase 2 — Core Platform, Auth, Catalog, and Admin CRUD

> Read `docs/CONTEXT.md` before starting — §6 governs this phase in full.
> Do not begin any later phase until the exit criteria below are all met.

---

## Why this file exists — a renumbering

The original Phase 3 was **SQL ↔ Chroma dual-write** (milestone 3 in
`docs/CONTEXT.md` §10, and the dual-write items in
`docs/phases/phase-02-platform.md`). It is **deferred**, not cancelled:
every product write must embed its text through Mesh `/v1/embeddings`, and
Phase 1 recorded that no free embedding model exists on Mesh and the account
has no balance (`docs/phases/phase-01-foundation.md`, decisions table).
Building the dual-write against an embedding call that cannot execute would
produce exactly the untestable half-feature CONTEXT §9 warns about.

**Behavioural tracking is now the active phase.** It is the right thing to
pull forward: it depends only on SQL, it feeds the behaviour engine that comes
next, and every hour of real browsing it captures makes the eventual
recommendation demo more convincing.

The choke point for the deferred work is already in place —
`app/services/product_service.py` carries the insertion points in its
docstrings, so dual-write lands there without touching any caller.

**Milestone numbering after this change:**

| # | Milestone | Phase file |
|---|-----------|------------|
| 1 | Repo, CI, Mesh verification | `phase-01-foundation.md` |
| 2 | Platform, auth, catalog, admin CRUD | `phase-02-platform.md` |
| 3 | **Behavioural event tracking** | **this file** |
| — | SQL ↔ Chroma dual-write | deferred — blocked on Mesh balance |
| 4+ | Behaviour engine, trigger engine, agent, dashboard | unchanged |

---

## Goal

Capture what a user actually does — what they view, search, click, dwell on and
bounce off — without ever making the interface wait for the network.

**Why this phase exists:** every downstream claim depends on this data. The
behaviour engine scores these rows, the trigger engine counts their delta, and
the intelligence dashboard proves the efficiency story by comparing events
captured against Mesh calls made. If tracking is lossy or blocking, everything
above it is either wrong or slow.

---

## Scope

In scope:

- `tracker.js` — client-side queue, batching, and the six DOM signals
- `app/schemas/event.py` — the batch request body
- `app/services/event_service.py` — bulk insert, one transaction
- `app/routes/events.py` — `POST /api/events/batch`, returns 202
- data attributes on the catalog, product card and product detail templates
- router registration in `app/main.py`

Explicitly out of scope — do **not** build these yet:

- the behaviour engine (weighting, recency decay, profile hash)
- the trigger engine (delta threshold, cooldown, cache decision)
- Chroma, embeddings, or any vector code
- LangGraph, agent nodes, prompts
- the dashboard, the intelligence panel, or any read API over events

Writing the rows is this phase. Reading them is the next one.

---

## Tasks

### 3.1 Tracker

`code/frontend/static/js/tracker.js` — one file, no dependencies, no build step.

Requirements, from CONTEXT §6 and architecture §3.1:

- in-memory queue; flush at **10 seconds or 20 events**, whichever comes first
- event types: `product_view`, `search`, `click`, `category_view`,
  `time_spent`, `scroll_depth`, `recommendation_click`, `quick_exit`
- scroll throttled; search input debounced at 500ms
- time-on-page accumulated via `visibilitychange`, **not** a polling timer
- a product view under 3 seconds emits `quick_exit` instead of `time_spent`
- flush on `pagehide` with `navigator.sendBeacon`
- nothing may block or await on the UI thread
- no-op cleanly when the user is logged out

### 3.2 Batch schema

`app/schemas/event.py` — a list of events, each with `event_type`, optional
`product_id`, optional `metadata`, and a client-side timestamp. Batch size is
capped in the schema so an oversized POST is rejected before it reaches a
handler.

### 3.3 Event service

`app/services/event_service.py` — insert a batch in **one** transaction.
Validate `event_type` against the known set and **drop** unknown types rather
than failing the whole batch: one stale client must not cost a user their
entire browsing session.

### 3.4 Ingest route

`app/routes/events.py` — `POST /api/events/batch`.

- 401 when there is no session
- 202 returned immediately
- the database write runs in a `BackgroundTask`, never on the request path
- oversized batches rejected

### 3.5 Template wiring

Load the tracker from `layouts/base.html` and add the data attributes it reads
to `pages/catalog.html`, `pages/product_detail.html` and
`partials/product_card.html`.

### 3.6 Router registration

Register the events router in `app/main.py`.

---

## Exit criteria

All must be true before the next phase begins:

- [x] browsing the catalog while logged in writes rows to `events`
- [x] a batch containing an unknown `event_type` stores the valid rows and drops
      only the bad one
- [x] `POST /api/events/batch` returns 202, and returns before the insert runs
      — measured p50 1.0ms / p95 1.1ms over 50 requests against the 20ms budget
- [x] the same POST while logged out returns 401 and writes nothing
- [x] a batch of more than 100 events is rejected (422 from the schema)
- [x] a product page left after 30+ seconds produces `time_spent`; one left
      inside 3 seconds produces `quick_exit`
- [ ] closing the tab flushes the queue via `sendBeacon` — no lost tail
      *(verified in the stub harness; still wants one real browser check)*
- [x] no `await` or synchronous XHR anywhere in `tracker.js`

---

## Decisions recorded in this phase

Fill these in as they are settled — later phases read this file.

| Item | Value |
|------|-------|
| Flush trigger | 10s since first queued event, or 20 events |
| Max batch accepted by the API | 100 events |
| Client queue cap | 100 events; oldest dropped beyond that |
| Authoritative event time | server `created_at`; client time kept in metadata |
| Unknown `event_type` | dropped, batch still stored |
| Retry on failed flush | none — events are lossy by design |

---

## Notes / issues encountered

- **A background task cannot borrow the request's session.** Since FastAPI
  0.106 a `yield` dependency is closed before background tasks run, so
  `store_events_in_background` opens its own `Session` from the engine. Passing
  `SessionDep` through would have worked in tests and failed in production.
- **Deleted products would have failed whole batches.** `events.product_id` is
  an enforced foreign key (SQLite `PRAGMA foreign_keys=ON`), so an event queued
  against a product an admin deletes mid-session raises `IntegrityError` and
  loses all 20 rows. The service now checks referenced ids in one query and
  drops only the orphans. This is the Phase 4 concern flagged in
  `product_service.delete_product` arriving early.
- **`quick_exit` is emitted on `pagehide`, not on tab-hide.** Finalising when
  the tab merely goes to the background would label anyone who glances at
  another tab after two seconds a bounce, poisoning a negative-weight signal.
  Hiding still flushes the queue by beacon; it just does not close the timer.
  Cost: a mobile browser killed without firing `pagehide` loses that page's
  timing event.
- **The client timestamp is not authoritative.** It is stored in the event's
  metadata as `client_ts`; `created_at` stays server-side, because a skewed
  client clock would otherwise distort recency decay in the behaviour engine.
- **`metadata` on the wire, `event_metadata` on the model.** The attribute is
  renamed because SQLAlchemy reserves `metadata` on declarative classes; the
  column and the JSON body both still say `metadata`.
- `recommendation_click` is emitted by the same delegated click handler when a
  card carries `data-track-source="recommendation"`. No template sets that yet
  — the recommendation UI is a later phase — but it is one branch on a live
  code path, not a stub.
