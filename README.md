# SmartReco

## What SmartReco is

SmartReco is a course-marketplace web platform that models user intent by observing real-time behavioural interactions. Rather than relying on simple item-to-item similarity, it builds an evolving user interest profile to drive an agentic recommendation pipeline. The system produces catalog-grounded, highly persuasive course recommendations tailored to the learner's current journey.

---

## Architecture

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
                               │  Chroma / SQL   │
                               │   Retriever     │
                               └────────┬────────┘
                                        ▼
                               stored recommendation
                                        │
                                        ▼
                               USER DASHBOARD
                               + INTELLIGENCE PANEL

        Every AI operation ───────────► mesh_client.py ───► Mesh API
```

### System Layers

- **Event Tracking (Implemented):** Client-side tracking (`tracker.js`) queues user interaction events (searches, course views, dwell times, clicks) and flushes them in non-blocking batches to `POST /api/events/batch`.
- **Behaviour Engine (Implemented):** A deterministic Python module that processes recent events, applies interest action weights and recency time-decay functions, and computes an updated user interest profile without relying on LLM calls.
- **Trigger Engine (Implemented):** Evaluates accumulated interest profile changes against configurable delta thresholds and cooldown timers to decide when recommendation generation is necessary, preventing unnecessary AI API overhead.
- **LangGraph Agent (Implemented):** A stateful recommendation pipeline that plans semantic queries, retrieves candidates from vector storage, applies deterministic scoring and candidate filtering, and generates persuasive structured recommendations capped at two Mesh LLM calls.
- **Product Service Dual-Write (Implemented):** All product creates, updates, and deletes route through `app/services/product_service.py`, enforcing dual-write consistency between SQL and Chroma with transactional rollback.

---

## Tech stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| **Backend** | FastAPI | High-performance, asynchronous Python web framework for clean API routing. |
| **ORM** | SQLModel (SQLAlchemy) | Type-safe ORM offering Pydantic data validation and minimal query boilerplate. |
| **Database** | SQLite | Zero-setup relational storage ideal for evaluation; easily swapped via `DATABASE_URL`. |
| **AI Gateway** | Mesh API | Unified compliance gateway for all generative LLM chat completions (`plan_queries`, `generate`). |
| **Vector DB** | Chroma (`all-MiniLM-L6-v2` / Mesh) | Embedded local Chroma vector database (`chroma.sqlite3`). Currently operates using Chroma's local embedding model as Mesh embeddings require account balance. Switching back to Mesh embeddings is a single env setting (`EMBEDDING_BACKEND=mesh`) plus a reindex. |

> **Note on Vector Index Embeddings vs Generative LLM Calls:**  
> All 72 catalog products are embedded and indexed in Chroma (`data/chroma/chroma.sqlite3`). Because Mesh embeddings require paid account balance (`402 spend_limit_exceeded`), the vector store automatically runs via Chroma's local ONNX embedding model (`EMBEDDING_BACKEND=auto`). Setting `EMBEDDING_BACKEND=mesh` switches back to Mesh embeddings without code changes. Every generative LLM call (`plan_queries`, `generate`) routes exclusively through the Mesh API.
| **Agent Framework** | LangGraph | Explicit, traceable state-graph engine for orchestrating query planning and generation. |
| **Frontend** | Jinja2 + Vanilla CSS/JS | Server-rendered HTML templates with responsive styling and zero client build toolchain. |
| **Authentication** | Session Cookie + bcrypt | Tamper-proof session cookie handling paired with secure password hashing (`bcrypt`). |

---

## Setup

Follow these exact steps from the project root directory to set up and run SmartReco:

```bash
# 1. Clone the repository and enter the directory
git clone <repository_url>
cd Hackathon

# 2. Create and activate a Python virtual environment
python3 -m venv code/backend/.venv
source code/backend/.venv/bin/activate

# 3. Install dependencies
pip install -r code/backend/requirements.txt

# 4. Copy the environment configuration file
cp code/backend/.env.example code/backend/.env
```

Open `code/backend/.env` in your text editor and set your `MESH_API_KEY`:
```env
MESH_API_KEY=your_mesh_api_key_here
```

Seed the product catalog and default demo accounts:
```bash
# 5. Populate SQLite database with seed courses and admin/user accounts
PYTHONPATH=code/backend python3 scripts/seed_products.py

# 6. Launch the server from project root
python main.py
```

The web application will be accessible at [http://127.0.0.1:8000](http://127.0.0.1:8000).

---

## Mesh API compliance

SmartReco strictly enforces Mesh API compliance across all artificial intelligence operations:

- **Single Gateway Module:** Every generative chat completion and embedding call routes exclusively through `app/ai/mesh_client.py`.
- **No Alternative Clients:** No other file or module in the codebase is permitted to instantiate an LLM or embedding provider client (enforcing rules R1 & R2).
- **Resilience:** `MeshClient` implements exponential backoff retries via `tenacity` and raises a typed `MeshUnavailableError` upon failure. System fallbacks serve stored recommendations without calling non-Mesh providers.

---

## Measured efficiency

*Measured live via 4-persona simulation (`scripts/simulate_behavior.py`) — 109 total events, running HTTP server, `ChromaRetriever` + local ONNX embeddings, `TRIGGER_DELTA_THRESHOLD=2.0`, `RETRIEVAL_SIMILARITY_THRESHOLD=0.30`:*

- **LLM Calls per 100 Events:** **1.83** — trigger engine skipped or cache-hit 95% of all evaluations. Only 1 of 41 evaluations resulted in a full agent run.
- **p95 Tracking Latency:** **3.25 ms** for `POST /api/events/batch` (FastAPI `BackgroundTask` decouples DB writes from the response path).
- **Vector Retrieve Latency:** **65–174 ms** (post-startup warm). Before the fix: 3,435–3,705ms. Root cause was ONNX model cold-load; fixed by module-level singleton and `vector_store.warm()` at startup.
- **Retrieval Funnel:** `22 retrieved → 16 filtered (≥ 0.30 similarity) → 8 reranked → 2 recommended`.
- **Hard Budget:** Maximum **2 Mesh LLM calls per agent run** (1 query planner + 1 generator). Zero non-Mesh providers.

---

## Bonus features

- [x] **APScheduler Daily Digest (`app/tracking/scheduler.py`):** Background cron job running daily at 17:00 local time (env-gated via `ENABLE_SCHEDULER`).
- [x] **LangSmith Tracing Integration:** Trace visualization for LangGraph workflows (env-gated via `LANGSMITH_TRACING`).
- [x] **Intelligence Dashboard (`/intelligence`):** Real-time interest profile progress bars, trigger evaluation status, retrieval funnel breakdown, and execution audit log table.
