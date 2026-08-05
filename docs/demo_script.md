# SmartReco — 3-Minute Demo Video Script

This document outlines the shot-by-shot script and walkthrough for recording the 3-minute submission video for SmartReco.

---

## Pre-Recording Checklist

Ensure all items are verified before pressing record:

- [ ] **Reset Seed Data:** Run `python scripts/seed_products.py --reset` to ensure a clean catalog and fresh test accounts.
- [ ] **Browser Window & Zoom:** Set browser resolution to 1920x1080 (or 16:9 aspect ratio) with zoom at 100% or 110% for crisp readability.
- [ ] **Clean Browser State:** Close all personal tabs, hide bookmarks bar, disable extensions, and clear session cookies.
- [ ] **Terminal Font Size:** Set terminal font size to 16pt+ with a high-contrast dark theme.
- [ ] **Server Running:** Ensure `python main.py` is running locally without debug clutter or terminal warnings.

---

## Video Script (0:00 - 3:00)

> **Note on Implementation Status:** Segments marked with **[PLANNED FEATURE]** depend on components that are not yet built (event tracking JS, behaviour engine, trigger engine, LangGraph agent, dashboard, background email scheduler, LangSmith tracing).

| Timestamp | What's on screen | What narrator says | What to click | Status |
|-----------|------------------|--------------------|---------------|--------|
| **0:00 - 0:20** | SmartReco landing page & course catalog | *"Most recommendation widgets just show static item-to-item similarity. SmartReco is a behavioural intelligence system that models user intent in real time to deliver catalog-grounded, highly persuasive recommendations."* | Hover over course catalog grid. | **[PARTIALLY BUILT]** (Catalog & Auth built; live rec banner planned) |
| **0:20 - 1:00** | Logged in as Persona A (Data Engineer). User opens Data Engineering courses, views descriptions, and dwells on ETL / SQL topics. | *"Here we log in as a data engineer. As the user searches for SQL and pipeline optimization courses, SmartReco implicitly tracks engagement without blocking the UI thread."* | Click into "Data Pipeline Engineering" course, scroll through details, return to catalog. | **[PLANNED FEATURE]** (Auth & Catalog built; tracking & profile generation planned) |
| **1:00 - 1:40** | Intelligence Panel / User Profile view showing interest profile weights shifting live towards "Agentic AI" as the user starts searching LLM agent courses. | *"Now on the SAME account, the user's intent shifts towards Agentic AI. Notice how our deterministic behaviour engine updates the interest profile in real time and triggers a fresh recommendation."* | Search for "LangGraph" in search bar, click "Building Agentic AI Systems", then refresh Intelligence Dashboard. | **[PLANNED FEATURE]** (Search & Catalog built; live profile shift & agent generation planned) |
| **1:40 - 2:00** | Architecture diagram overlay (`docs/architecture.md` pipeline). | *"Under the hood, SmartReco uses a deterministic behaviour engine to calculate interest weights and recency decay—requiring zero LLM calls."* | Point cursor to Behaviour Engine box on diagram. | **[DOCS READY]** |
| **2:00 - 2:20** | Trigger & Caching Logic code snippet (`trigger_engine.py` & `agent_runs` table). | *"Our trigger engine evaluates accumulated delta threshold and cooldown rules. If the profile hasn't changed, we serve cached recommendations with exactly zero AI calls."* | Highlight delta threshold check in code/diagram. | **[PLANNED FEATURE]** (Trigger engine planned) |
| **2:20 - 2:40** | LangSmith Trace visualizer showing LangGraph agent execution. | *"When a generation is triggered, our LangGraph agent executes query planning, vector retrieval, candidate filtering, and structured generation—strict budget of 2 Mesh LLM calls."* | Click into LangSmith trace tree, expanding the 2 LLM nodes. | **[PLANNED FEATURE]** (LangGraph agent & tracing planned) |
| **2:40 - 3:00** | Inbox window receiving a scheduled behavioural recommendation email. | *"Finally, background triggers can dispatch personalized recommendation digest emails to keep learners engaged right when their interest peaks. Thank you for watching!"* | Open email client tab showing formatted recommendation message. | **[PLANNED FEATURE]** (Email digest planned) |

---

## Segment Implementation Summary

- **0:00 - 0:20 (Problem Statement):** UI Scaffold, Catalog, and Auth are **[BUILT]**.
- **0:20 - 1:00 (Persona A Browsing):** Event tracking pipeline and live recommendation display are **[PLANNED]**.
- **1:00 - 1:40 (Behaviour Shift):** Live interest profile calculation and agentic recommendation generation are **[PLANNED]**.
- **1:40 - 2:20 (Architecture & Triggering):** System architecture is **[DESIGNED]**; trigger/caching logic is **[PLANNED]**.
- **2:20 - 3:00 (Observability & Email Digest):** LangGraph agent, LangSmith tracing, and scheduled email delivery are **[PLANNED]**.
