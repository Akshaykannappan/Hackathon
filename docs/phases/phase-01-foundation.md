# Phase 1 — Foundation, CI, and Mesh Verification

**Status:** ☐ Not started
**Estimated effort:** half a day
**Prerequisite:** none — this is the first phase

> Read `docs/CONTEXT.md` before starting. Do not begin any later phase until
> the exit criteria below are all met.

---

## Goal

Establish a repository that passes the competition's automated checks, and
prove that Mesh API works for both chat completion and embeddings before a
single line of application logic is written.

**Why this phase exists:** the entire architecture assumes embeddings route
through Mesh. If that assumption is wrong, it is far cheaper to discover it
now than in week two. Everything downstream depends on this being verified.

---

## Scope

In scope:

- repository scaffold and `.gitignore`
- dependency manifest
- centralised configuration
- the Mesh client — the only AI entry point in the project
- a verification script
- a minimal FastAPI app that boots
- CI workflow committed and passing

Explicitly out of scope — do **not** build these yet:

- database models or migrations
- authentication
- any route beyond `/health`
- Chroma or any vector store code
- LangGraph, agent nodes, prompts beyond a trivial test string
- templates, static files, tracking

---

## Tasks

### 1.1 Repository skeleton

Run `scaffold.sh` from the project root. Confirm `.gitignore` contains `.env`.

### 1.2 CI workflow

Download the official workflow file from the URL in the challenge brief and
place it at `.github/workflows/smartreco-checks.yml`.

**Read the YAML before committing it.** GitHub Actions workflows can read
repository secrets. Confirm it only runs checks and reports back — nothing
that exfiltrates `MESH_API_KEY` to an unexpected destination.

Add repository secrets under Settings → Secrets and variables → Actions:

- `MESH_API_KEY`
- `SUBMISSION_TOKEN`

### 1.3 Dependencies

`code/backend/requirements.txt`:

```
fastapi
uvicorn[standard]
sqlmodel
jinja2
python-multipart
passlib[bcrypt]
itsdangerous
pydantic-settings
python-dotenv
openai
chromadb
langgraph
httpx
tenacity
pytest
```

The critical checker looks for a web framework and an LLM client. `fastapi`
and `openai` satisfy this.

### 1.4 Configuration

`app/core/config.py` — a pydantic-settings `Settings` class covering every key
in `.env.example`. Instantiate once, import everywhere.

No `os.getenv` anywhere else in the codebase, now or later.

### 1.5 Mesh client

`app/ai/mesh_client.py` — a single `MeshClient` class.

Requirements:

- constructs one `OpenAI` client pointed at `MESH_BASE_URL`
- `chat(messages, **kwargs) -> str`
- `chat_json(messages, schema_hint) -> dict` — strips markdown fences, parses,
  raises on invalid JSON
- `embed(texts: list[str]) -> list[list[float]]` — accepts a list and sends it
  as a **single batched request**; the returned order matches input order
- both wrapped with `tenacity` exponential backoff, 3 attempts
- raises a typed `MeshUnavailableError` after final failure
- never falls back to a non-Mesh provider

This file is the only place in the entire project permitted to construct an AI
client. Enforce this in review.

### 1.6 Verification script

`scripts/verify_mesh.py` must:

1. fail loudly and clearly if `MESH_API_KEY` is missing
2. call `GET /v1/models` and print every embedding model with its id,
   pricing, and `is_free` flag
3. perform one chat round-trip and print the response
4. perform one **batched** embedding call with 3 strings and print the vector
   dimension and the count returned
5. exit non-zero on any failure

### 1.7 Minimal app

`app/main.py` — FastAPI instance, `GET /health` returning
`{"status": "ok"}`. Nothing else.

---

## Exit criteria

All must be true before Phase 2 begins:

- [x] `bash scaffold.sh` has been run; structure matches `docs/architecture.md`
- [x] `.gitignore` includes `.env`; no secret is committed anywhere in history
- [x] CI checks show green on the latest commit in the Actions tab
- [ ] `python scripts/verify_mesh.py` succeeds and prints a real vector dimension
- [ ] the chosen embedding model is recorded in `.env.example` and noted below
- [x] `uvicorn app.main:app` boots and `/health` responds
- [x] `MeshClient` is the only class constructing an AI client
- [x] no `os.getenv` outside `config.py`

---

## Decisions recorded in this phase

Fill these in as they are settled — later phases depend on them.

| Item | Value |
|------|-------|
| Embedding model chosen | NOT YET VERIFIED — blocked on Mesh account balance |
| Embedding dimension | NOT YET VERIFIED |
| Is it free? | No free embedding models available on Mesh |
| Chat model chosen | `minimax/m2-her` (verified working, free tier) |

---

## Notes / issues encountered

- Mesh returns a bare JSON array from `/v1/models`, not an OpenAI-style `{"data": [...]}` envelope.
- No free embedding models exist on Mesh; cheapest is `google/embeddinggemma-300m` at $0.002/1M, then `baai/bge-base-en-v1.5` and `sentence-transformers` models at $0.005/1M.
- Three free chat models: `minimax/m2-her`, `tencent/hy3`, `openai/omni-moderation-latest`.
- `.env` must be loaded by absolute path or the app breaks when run from the project root.
