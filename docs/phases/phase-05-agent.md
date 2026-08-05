# Phase 5 — LangGraph Agent, Vector Retrieval, & Persuasive Generation

**Status:** ☑ Complete — 49 tests passing, verified end-to-end with KeywordRetriever fallback  
**Estimated effort:** 2 days  
**Prerequisite:** Phase 4 — Behaviour Engine & Tracking  

> Read `docs/CONTEXT.md` (§4 pipeline, §9 anti-patterns) and `docs/architecture.md` (§3.4 the agent, §3.5 reranking, §3.6 generation and grounding, §6 failure handling) before starting.

---

## Goal

Build the LangGraph recommendation agent: consume the user's weighted interest profile, plan semantic retrieval queries, retrieve candidates from Chroma vector storage (or KeywordRetriever fallback), filter and rerank candidates deterministically in Python, generate persuasive catalog-grounded copy, validate product IDs against retrieved sets, and store the resulting recommendation and agent execution trace.

**Hard LLM Budget:** Exactly **two Mesh LLM calls per run** — Call #1 for the query planner, and Call #2 for the generator. Every other node in the graph is deterministic Python logic. Adding a third LLM call requires explicit justification against the competition efficiency criterion.

---

## Scope

In scope:

- Vector storage wrapper (`app/services/vector_store.py`) connecting Chroma to Mesh embeddings
- Chroma dual-write integration inside `app/services/product_service.py` (create, update, delete sync with rollback on failure)
- Drift recovery script (`scripts/reindex_vectors.py`) to rebuild Chroma vector collections from SQL records
- Typed graph state definition (`app/agent/state.py`)
- LangGraph node implementations (`app/agent/nodes.py`) for analysis, query planning, retrieval, relevance filtering, deterministic broadening, reranking, generation, validation, and storage
- LangGraph graph assembly and conditional wiring (`app/agent/graph.py`) with a single-pass deterministic broadening loop
- Centralized LLM prompt templates (`app/ai/prompts.py`)
- Cold-start recommendation strategy (zero LLM calls for new users with weak profiles)
- Robust Mesh failure handling and degraded execution logging to `agent_runs`

Explicitly out of scope — do **not** build these yet:

- Intelligence Dashboard and live agent run visualizer (Phase 6)
- APScheduler automated background trigger scheduling (Phase 6)
- LangSmith tracing integration (Phase 6)

---

## Tasks

### 5.1 Vector Store Wrapper (`app/services/vector_store.py`)

Implement `VectorStoreService` wrapping Chroma:

- Uses `app/ai/mesh_client.py` for all vector embedding operations
- Enforces the document ID convention: Chroma document ID equals the SQL product primary key as a string (e.g., `"127"`)
- Methods for batch upsert, metadata filter search, and item deletion

### 5.2 Product Service Dual-Write (`app/services/product_service.py`)

Integrate Chroma dual-write into `product_service.py` across all mutation methods:

- `create()`: Inserts SQL record and upserts embedding document into Chroma. If embedding/Chroma call fails, rolls back the SQL transaction.
- `update()`: Updates SQL record and re-embeds/upserts modified title, description, and metadata to Chroma.
- `delete()`: Deletes SQL record and removes document ID from Chroma.

### 5.3 Vector Reindexing Script (`scripts/reindex_vectors.py`)

Create a CLI utility to re-index all SQL products into Chroma:

- Reads all products from SQLite database
- Batches product text (`title` + `description` + `category`) through Mesh embedding client
- Rebuilds Chroma collection from scratch to recover from any store drift

### 5.4 Agent State Definition (`app/agent/state.py`)

Define `AgentState` as a typed Pydantic/TypedDict class:

- Holds `user_id`, `profile`, `profile_hash`, `queries`, `retrieved_candidates`, `filtered_candidates`, `reranked_candidates`, `generated_message`, `valid_product_ids`, `execution_metrics`, and `error`

### 5.5 Agent Graph Nodes (`app/agent/nodes.py`)

Implement individual agent nodes:

- `analyze_profile`: Reads recent events, interest profile, and previously recommended product IDs (Python).
- `plan_queries`: Mesh LLM Call #1 — translates interest profile into 2–3 targeted semantic search queries.
- `retrieve`: Embeds queries via Mesh, executes multi-query Chroma search, and deduplicates candidates (Python + Mesh Embeddings).
- `filter_relevance`: Applies minimum similarity threshold filtering (Python).
- `broaden`: Deterministically expands search queries if retrieved set is insufficient (Python — **no LLM**).
- `rerank`: Computes multi-factor reranking scores (semantic similarity, interest match, recency signal, level fit, negative penalties) (Python).
- `generate`: Mesh LLM Call #2 — generates structured JSON response containing persuasive copy and product IDs.
- `validate`: Unconditionally validates returned product IDs against the retrieved set, dropping ungrounded/invented IDs (Python).
- `store`: Persists final recommendation and creates structured `agent_run` log entry (Python).

### 5.6 Agent Graph Assembly (`app/agent/graph.py`)

Assemble and compile the LangGraph workflow:

- Wire state edges between nodes in logical order
- Implement conditional edge after `filter_relevance`: if candidates < minimum, route to `broaden` for **one single pass**, then re-retrieve without calling an LLM
- Enforce strict single-loop cap to maintain graph determinism and performance budget

### 5.7 Centralized Prompts (`app/ai/prompts.py`)

Create `app/ai/prompts.py` storing structured system and user prompt templates:

- Query planner prompt: Instructs model to output a JSON array of search strings based on user interest signals.
- Recommendation generator prompt: Provides qualitative interest profile summary, recent behavioural signals, and numbered candidate courses. Demands structured JSON output containing `message`, `products`, and `reasoning`.

### 5.8 Cold Start Strategy

Implement cold start branching in `analyze_profile`:

- If accumulated profile signal < minimum threshold, skip LLM nodes entirely
- Select top-rated/diverse products across distinct categories deterministically
- Return pre-defined cold start copy (*"SmartReco doesn't know you yet — pick a direction"*) with zero LLM calls

### 5.9 Mesh Failure & Degradation Handling

Implement graceful degradation wrappers for LLM nodes:

- Wrap Mesh calls with exponential backoff retries (3 attempts)
- On terminal Mesh failure, fallback to serving the user's last stored recommendation
- Log run status as `degraded` or `failed` in `agent_runs` with detailed error stack trace

---

## Exit criteria

All must be true before Phase 6 begins:

- [x] Two accounts with different browsing histories receive genuinely distinct course recommendations
- [x] Product ID validation strictly drops any invented or ungrounded product ID returned by the LLM
- [x] Deleting a product via `product_service` removes it from both SQLite and Chroma
- [x] A brand-new user with zero events receives diverse cold-start recommendations with zero LLM calls
- [x] A simulated Mesh API outage falls back to stored recommendations and logs a `degraded` `agent_run` entry
- [x] `scripts/reindex_vectors.py` successfully rebuilds Chroma from SQLite without errors
- [x] Total LLM calls per recommendation run never exceeds 2

---

## Decisions recorded in this phase

Fill these in as they are settled — later phases depend on them.

| Item | Value |
|------|-------|
| Embedding model | `all-MiniLM-L6-v2` (Chroma local ONNX) / `openai/text-embedding-3-small` (Mesh API when balance exists) |
| Embedding dimension | `384` (local) / `1536` (Mesh) |
| Chroma collection name | `smartreco_products` |
| Chat model for the planner | `minimax/m2-her` |
| Chat model for the generator | `minimax/m2-her` |
| Similarity threshold | `0.20` |
| Retrieval top-k | `12` |

---

## Notes / issues encountered

- **Chroma Local & Mesh Embedding Backends:** To ensure a fully queried vector database (`chroma.sqlite3`) exists without requiring Mesh API embedding balance (`402 spend_limit_exceeded`), `VectorStore` supports both `mesh` embeddings and Chroma's bundled `local` ONNX model (`all-MiniLM-L6-v2`). `EMBEDDING_BACKEND=auto` probes Mesh once and falls back to local embeddings. Switching to Mesh embeddings is a single env setting (`EMBEDDING_BACKEND=mesh`) plus a reindex.
- **Mesh LLM Compliance:** Every generative LLM call (`plan_queries` and `generate`) routes exclusively through the Mesh API.
- **Product ID Grounding & Validation:** The `validate` node unconditionally rejects any product ID returned by the generator LLM that was not present in the candidate set. If fewer than 2 valid IDs survive, the run is marked `degraded` and the user's previous recommendation is retained.
- **Strict 2-Call LLM Budget:** The graph execution uses at most 2 Mesh LLM calls (`plan_queries` and `generate`). Refinement and query broadening are handled deterministically in Python (`broaden` node) and capped at 1 pass.
