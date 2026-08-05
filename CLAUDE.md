# CLAUDE.md

SmartReco — agentic behavioural recommendation platform.
Competition submission. The repository is the deliverable.

## Before doing anything

1. Read `docs/CONTEXT.md` — rules, locked decisions, anti-patterns.
   It is the source of truth. Do not propose alternatives to settled decisions.
2. Read `docs/architecture.md` — how the system works end to end.
3. Read the **current phase file** under `docs/phases/`. Work only within its
   scope. Do not build ahead into later phases.

## Standing rules

- Every AI call — chat and embeddings — goes through `app/ai/mesh_client.py`
  to Mesh API. No exceptions, no other provider, ever.
- Maximum 2 Mesh LLM calls per recommendation run.
- Anything Python can compute deterministically must not use an LLM.
- No secrets in the repository. `.env` is gitignored.
- No stubbed features, no hardcoded recommendations, no unused clients.
- All `.md` files live in `docs/`. Only `README.md` and this file sit at root.

## Current phase

**Phase 7 — Polish, Tracing, Scheduler, Simulation & Efficiency Metrics**
→ `docs/phases/phase-07-polish.md`

Update this section when a phase completes.
