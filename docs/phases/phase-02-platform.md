# Phase 2 — Core Platform, Auth, Catalog, and Admin CRUD

**Status:** ☐ Not started
**Estimated effort:** 1 day
**Prerequisite:** Phase 1 — Foundation, CI, and Mesh Verification

> Read `docs/CONTEXT.md` before starting. Do not begin any later phase until
> the exit criteria below are all met.

---

## Goal

Build the foundational domain models, authentication system, product catalog, and admin CRUD interface. Ensure the dual-write invariant between SQLite and Chroma vector storage is enforced through a centralized product service.

**Why this phase exists:** The recommendation engine relies on a populated product catalog and user identity context. Establishing clean data models, session authentication, and dual-write synchronization before building the behavioral tracking and recommendation pipeline prevents data corruption and architectural drift.

---

## Scope

In scope:

- SQLModel database schemas for all core tables (`users`, `products`, `events`, `recommendations`, `user_interest_profiles`, `agent_runs`)
- User authentication and session management (bcrypt password hashing, session cookies)
- Centralised product service (`services/product_service.py`) handling product mutations
- Dual-write synchronization between SQLite and Chroma vector DB (Chroma doc ID == SQL product primary key)
- Admin CRUD endpoints and Jinja2 views for catalog management (`user` vs `admin` roles)
- Seed script for catalog (60–100 products spanning 10 distinct categories)

Explicitly out of scope — do **not** build these yet:

- Event tracking pipeline and client-side event queueing (Phase 3)
- Trigger engine and interest profile calculation (Phase 3)
- LangGraph agent nodes and recommendation generation pipeline (Phase 4)
- Intelligence dashboard and agent run visualizer (Phase 5)

---

## Tasks

### 2.1 Database & SQLModel Schemas

Create SQLModel definitions in `app/models/`:

- `User`: `id`, `email`, `password_hash`, `role` (`user` / `admin`), `created_at`
- `Product`: `id`, `title`, `description`, `category`, `level`, `price`, `created_at`, `updated_at`
- `Event`: `id`, `user_id`, `event_type`, `product_id` (nullable), `metadata_json`, `created_at`
- `Recommendation`: `id`, `user_id`, `message`, `product_ids_json`, `interest_profile_json`, `trigger_reason`, `created_at`
- `UserInterestProfile`: `user_id`, `profile_json`, `profile_hash`, `last_generated_at`, `accumulated_delta`
- `AgentRun`: `id`, `user_id`, `trigger_reason`, `nodes_json`, `llm_calls`, `cache_hit`, `latency_ms`, `status`, `error`, `created_at`

### 2.2 Authentication & Sessions

Implement session-based authentication in `app/services/auth_service.py` and `app/api/auth.py`:

- Password hashing using `passlib[bcrypt]`
- Secure session cookie management using `itsdangerous`
- Registration, login, and logout endpoints (`POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`)
- Dependency injectors for current user (`get_current_user`) and admin authorization (`require_admin`)

### 2.3 Product Catalog Service & Dual-Write Sync

Implement `app/services/product_service.py`:

- Enforce the dual-write invariant: Chroma document ID equals the SQL product primary key as a string
- All product creations, updates, and deletions MUST route through `product_service.py`
- If Chroma vector embedding/upsert fails during write, roll back the SQL transaction or queue upsert for retry to maintain sync integrity
- Product search and retrieval methods combining SQL filtering and Chroma vector queries

### 2.4 Admin CRUD Routes & Interface

Build admin catalog management in `app/api/admin.py` and Jinja2 templates:

- Admin-only protection enforced via `require_admin` dependency
- Admin views for listing, creating, editing, and deleting catalog products
- Form handling and validation using Pydantic schemas

### 2.5 Catalog Seed Script

Create `scripts/seed_catalog.py`:

- Seeds 60–100 products across 10 distinct categories with realistic titles, descriptions, categories, and difficulty levels
- Generates vector embeddings for all seed products via Mesh API and populates Chroma
- Includes seed admin and default test user accounts

---

## Exit criteria

All must be true before Phase 3 begins:

- [ ] SQLModel database tables created and verified via SQLite inspection
- [ ] User registration, login, logout, and session authentication functioning with bcrypt hashing
- [ ] Role-based access control (`user` vs `admin`) enforced on admin endpoints
- [ ] `services/product_service.py` established as the single entry point for product mutations
- [ ] Dual-write invariant verified: SQL product IDs match Chroma document IDs 1:1
- [ ] Catalog seed script populates 60–100 products across 10 categories in both SQL and Chroma
- [ ] Admin CRUD views allow adding, editing, and removing catalog products with instant vector sync

---

## Decisions recorded in this phase

Fill these in as they are settled — later phases depend on them.

| Item | Value |
|------|-------|
| Password hashing algorithm | bcrypt (`passlib`) |
| Session management approach | `itsdangerous` session cookie |
| Total seed products populated | _to be filled_ |
| Total categories in catalog | _to be filled_ |

---

## Notes / issues encountered

_Append anything surprising here. Future phases read this file._
