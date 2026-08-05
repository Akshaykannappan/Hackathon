#!/usr/bin/env bash
# SmartReco — project scaffold
# Run once from the empty project root:  bash scaffold.sh
set -euo pipefail

echo "Scaffolding SmartReco..."

# ── directories ───────────────────────────────────────────────────────────────
mkdir -p .github/workflows
mkdir -p docs/phases
mkdir -p scripts
mkdir -p code/backend/app/{core,models,schemas,routes,services,ai,agent,tracking,utils}
mkdir -p code/backend/tests
mkdir -p code/backend/data
mkdir -p code/frontend/templates/{layouts,partials,pages,admin}
mkdir -p code/frontend/static/{js,css,img}

# ── python package markers ────────────────────────────────────────────────────
touch code/backend/app/__init__.py
for d in core models schemas routes services ai agent tracking utils; do
  touch "code/backend/app/$d/__init__.py"
done
touch code/backend/tests/__init__.py

# ── backend: core ─────────────────────────────────────────────────────────────
touch code/backend/app/core/config.py          # pydantic-settings, env only
touch code/backend/app/core/database.py        # engine, session, init_db
touch code/backend/app/core/security.py        # bcrypt, session cookie helpers
touch code/backend/app/core/dependencies.py    # current_user, require_admin

# ── backend: models (SQLModel tables) ─────────────────────────────────────────
touch code/backend/app/models/user.py
touch code/backend/app/models/product.py
touch code/backend/app/models/event.py
touch code/backend/app/models/recommendation.py
touch code/backend/app/models/interest_profile.py
touch code/backend/app/models/agent_run.py

# ── backend: schemas (pydantic i/o) ───────────────────────────────────────────
touch code/backend/app/schemas/auth.py
touch code/backend/app/schemas/product.py
touch code/backend/app/schemas/event.py
touch code/backend/app/schemas/recommendation.py

# ── backend: routes ───────────────────────────────────────────────────────────
touch code/backend/app/routes/auth.py
touch code/backend/app/routes/catalog.py
touch code/backend/app/routes/admin.py
touch code/backend/app/routes/events.py         # POST /api/events/batch
touch code/backend/app/routes/recommendations.py
touch code/backend/app/routes/intelligence.py   # the visible-intelligence panel

# ── backend: services (business logic) ────────────────────────────────────────
touch code/backend/app/services/product_service.py    # THE dual-write chokepoint
touch code/backend/app/services/vector_store.py       # Chroma wrapper
touch code/backend/app/services/event_service.py
touch code/backend/app/services/behavior_engine.py    # weighted profile + decay
touch code/backend/app/services/trigger_engine.py     # delta, cooldown, hash, cache
touch code/backend/app/services/reranker.py           # deterministic scoring
touch code/backend/app/services/recommendation_service.py

# ── backend: ai (the ONLY place Mesh is touched) ──────────────────────────────
touch code/backend/app/ai/mesh_client.py       # chat + embeddings + retry/backoff
touch code/backend/app/ai/prompts.py

# ── backend: agent (LangGraph) ────────────────────────────────────────────────
touch code/backend/app/agent/graph.py          # graph wiring
touch code/backend/app/agent/state.py          # typed AgentState
touch code/backend/app/agent/nodes.py          # planner / retrieve / filter / rerank / generate / validate

# ── backend: scheduler (bonus) ────────────────────────────────────────────────
touch code/backend/app/tracking/scheduler.py   # APScheduler daily digest

# ── backend: entrypoint & config ──────────────────────────────────────────────
touch code/backend/app/main.py
touch code/backend/requirements.txt
touch code/backend/.env.example

# ── tests ─────────────────────────────────────────────────────────────────────
touch code/backend/tests/test_dual_write_sync.py
touch code/backend/tests/test_behavior_engine.py
touch code/backend/tests/test_trigger_engine.py
touch code/backend/tests/test_validation.py

# ── frontend ──────────────────────────────────────────────────────────────────
touch code/frontend/templates/layouts/base.html
touch code/frontend/templates/partials/{navbar.html,product_card.html,rec_card.html}
touch code/frontend/templates/pages/{login.html,register.html,catalog.html,product_detail.html,dashboard.html,intelligence.html}
touch code/frontend/templates/admin/{products.html,product_form.html}
touch code/frontend/static/js/tracker.js       # queue + throttle + sendBeacon
touch code/frontend/static/css/main.css

# ── scripts ───────────────────────────────────────────────────────────────────
touch scripts/verify_mesh.py                   # milestone 1 — run this FIRST
touch scripts/seed_products.py                 # 60-100 products, 10 categories
touch scripts/reindex_vectors.py               # rebuild Chroma from SQL
touch scripts/simulate_behavior.py             # demo personas for the video

# ── docs (every .md lives here except README.md and CLAUDE.md) ────────────────
# CONTEXT.md, architecture.md and phase-01 are provided — do not overwrite them.
touch docs/efficiency_metrics.md
touch docs/demo_script.md

# ── root files ────────────────────────────────────────────────────────────────
touch README.md

cat > .gitignore <<'EOF'
# secrets
.env
.env.*
!.env.example

# python
__pycache__/
*.py[cod]
.venv/
venv/
*.egg-info/
.pytest_cache/
.mypy_cache/

# data
*.db
*.sqlite3
code/backend/data/
chroma/
.chroma/

# os / editor
.DS_Store
.idea/
.vscode/
EOF

cat > code/backend/.env.example <<'EOF'
MESH_API_KEY=rsk_your_key_here
MESH_BASE_URL=https://api.meshapi.ai/v1
MESH_CHAT_MODEL=openai/gpt-4o-mini
MESH_EMBEDDING_MODEL=openai/text-embedding-3-small

DATABASE_URL=sqlite:///./data/smartreco.db
CHROMA_PERSIST_DIR=./data/chroma

SESSION_SECRET=change-me

TRIGGER_DELTA_THRESHOLD=10.0
TRIGGER_COOLDOWN_MINUTES=10

# bonus
LANGSMITH_API_KEY=
LANGSMITH_TRACING=false
EOF

echo ""
echo "Done. Structure created:"
echo ""
find . -type d -not -path '*/.git/*' | sort | sed 's|[^/]*/|  |g'
echo ""
echo "Next steps:"
echo "  1. Place CLAUDE.md at the project root"
echo "  2. Place CONTEXT.md, architecture.md in docs/"
echo "  3. Place phase-01-foundation.md in docs/phases/"
echo "  4. Download the official workflow into .github/workflows/smartreco-checks.yml"
echo "  5. Read that YAML, then commit. Add MESH_API_KEY + SUBMISSION_TOKEN secrets."
echo "  6. Fill scripts/verify_mesh.py and run it before writing anything else"
