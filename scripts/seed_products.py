"""Seed the catalog and the two demo accounts.

SQL only — Phase 3 adds the Chroma dual-write inside `product_service`, and this
script will pick it up for free because it never writes to the table directly.

70 courses across 10 categories. The spread matters: retrieval only looks
convincing when the catalog contains genuinely irrelevant alternatives that the
agent has to *not* pick (CONTEXT §8).

    python scripts/seed_products.py            # seed; no-op if products exist
    python scripts/seed_products.py --reset    # delete every product, then seed
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "code" / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from sqlmodel import Session, select  # noqa: E402

from app.core.database import engine, init_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import ROLE_ADMIN, ROLE_USER, Product, User  # noqa: E402
from app.schemas.auth import RegisterRequest  # noqa: E402
from app.schemas.product import ProductCreate  # noqa: E402
from app.services import product_service  # noqa: E402

ADMIN_EMAIL = "admin@smartreco.dev"
ADMIN_PASSWORD = "admin12345"
USER_EMAIL = "user@smartreco.dev"
USER_PASSWORD = "user12345"

# (title, description, level, price)
CourseRow = tuple[str, str, str, float]

CATALOG: dict[str, list[CourseRow]] = {
    "Agentic AI": [
        (
            "Building Agentic AI Systems with LangGraph",
            "Design stateful agent graphs with explicit nodes, conditional edges and typed state. "
            "You build a research agent that plans its own queries, retrieves evidence, critiques its "
            "draft and loops until a quality threshold is met.",
            "advanced",
            149.0,
        ),
        (
            "Multi-Agent Orchestration Patterns",
            "Coordinate specialised agents through supervisor, hierarchical and blackboard patterns. "
            "Covers task decomposition, message passing between agents, and the failure modes that "
            "appear once more than three agents share a workspace.",
            "advanced",
            179.0,
        ),
        (
            "Tool Use and Function Calling for LLM Agents",
            "Give a language model hands: schema design for tools, argument validation, and safe "
            "execution boundaries. You will wire an agent to a database, an HTTP API and a file system, "
            "then handle the malformed calls it inevitably produces.",
            "intermediate",
            99.0,
        ),
        (
            "Agent Memory: Short-Term, Episodic and Semantic",
            "Agents forget, and the fix is architectural rather than a bigger context window. "
            "Compare scratchpad state, summarised episodic history and vector-backed semantic recall, "
            "and learn when each one earns its latency cost.",
            "intermediate",
            119.0,
        ),
        (
            "Evaluating and Debugging Autonomous Agents",
            "Non-deterministic systems need evaluation harnesses, not spot checks. Build trajectory "
            "traces, node-level latency budgets and regression suites that catch a silently degraded "
            "agent before your users do.",
            "advanced",
            139.0,
        ),
        (
            "Introduction to AI Agents",
            "A gentle first tour of what separates an agent from a chatbot: perception, planning, "
            "action and feedback. No prior machine learning experience assumed, and every example runs "
            "on a laptop.",
            "beginner",
            49.0,
        ),
        (
            "Planning and Reasoning Loops: ReAct, Reflexion and Tree of Thought",
            "Work through the reasoning strategies that let a model recover from its own mistakes. "
            "You implement each loop by hand, measure the token cost, and learn which problems justify "
            "the extra inference calls.",
            "advanced",
            159.0,
        ),
    ],
    "RAG": [
        (
            "Retrieval-Augmented Generation from Scratch",
            "Build a complete RAG pipeline without a framework: ingestion, chunking, embedding, "
            "retrieval and grounded generation. Understanding every seam is what lets you debug the "
            "thing when answers start drifting.",
            "intermediate",
            129.0,
        ),
        (
            "Vector Databases in Production: Chroma, pgvector and Beyond",
            "Compare persistence models, index types and metadata filtering across the major vector "
            "stores. Covers keeping a vector index in sync with a relational source of truth, and "
            "recovering when the two disagree.",
            "intermediate",
            139.0,
        ),
        (
            "Chunking Strategies That Actually Improve Recall",
            "Fixed windows, semantic splits, sentence overlap and parent-document retrieval, measured "
            "against a real evaluation set. You will see why the default 1000-character chunk quietly "
            "destroys answer quality on structured documents.",
            "beginner",
            59.0,
        ),
        (
            "Hybrid Search: Combining BM25 with Dense Retrieval",
            "Keyword search finds exact identifiers; embeddings find meaning. Learn reciprocal rank "
            "fusion and score normalisation so a query containing a product code and a vague intent "
            "returns both kinds of match.",
            "advanced",
            149.0,
        ),
        (
            "Reranking and Relevance Tuning for RAG Pipelines",
            "Retrieval gets you candidates; reranking decides what the model actually sees. Build "
            "cross-encoder and deterministic weighted rerankers, then tune thresholds against "
            "precision and recall you can defend.",
            "advanced",
            159.0,
        ),
        (
            "Grounding and Hallucination Control",
            "Techniques for forcing a model to answer only from supplied evidence: citation "
            "enforcement, ID validation and refusal behaviour. You will build a validator that rejects "
            "any generated reference not present in the retrieved set.",
            "intermediate",
            119.0,
        ),
        (
            "Embeddings Explained: Similarity, Dimensions and Drift",
            "What a vector actually encodes, why cosine similarity behaves the way it does, and how "
            "model upgrades silently invalidate an existing index. Includes a practical guide to "
            "re-embedding a live corpus without downtime.",
            "beginner",
            69.0,
        ),
    ],
    "Machine Learning": [
        (
            "Machine Learning Foundations with scikit-learn",
            "Supervised learning end to end: train/test discipline, regression, classification and "
            "the bias-variance trade-off. Every concept is introduced through a dataset you fit, break "
            "and then repair.",
            "beginner",
            79.0,
        ),
        (
            "Deep Learning with PyTorch",
            "Tensors, autograd, and the training loop written by hand before any abstraction is "
            "introduced. You finish by training a convolutional network and diagnosing why it "
            "overfits.",
            "intermediate",
            149.0,
        ),
        (
            "Feature Engineering for Tabular Data",
            "Encoding, scaling, interaction terms and target leakage, with an emphasis on what "
            "survives contact with production data. Gradient-boosted trees still win on tabular "
            "problems, and features are why.",
            "intermediate",
            99.0,
        ),
        (
            "Model Evaluation, Cross-Validation and Leakage",
            "The metric you choose determines the model you ship. Covers stratified and time-aware "
            "splits, calibration, and the subtle leaks that produce a brilliant offline score and a "
            "useless deployed model.",
            "beginner",
            69.0,
        ),
        (
            "Time Series Forecasting",
            "Seasonality, stationarity and lag features, from classical ARIMA through gradient "
            "boosting on engineered windows. Includes backtesting protocols that respect the arrow of "
            "time.",
            "intermediate",
            129.0,
        ),
        (
            "Transformers and Attention Mechanisms",
            "Build a transformer block from scratch: multi-head attention, positional encoding and "
            "residual streams. By the end you can read a modern architecture paper and know exactly "
            "which part is novel.",
            "advanced",
            169.0,
        ),
        (
            "MLOps: Deploying and Monitoring Models",
            "Model registries, reproducible training, shadow deployments and drift detection. Focuses "
            "on the operational half of machine learning, where most projects actually fail.",
            "advanced",
            159.0,
        ),
    ],
    "Data Engineering": [
        (
            "Building Batch Data Pipelines with Airflow",
            "Author idempotent DAGs, manage dependencies and backfill history without corrupting "
            "downstream tables. Covers sensors, task retries and the scheduling semantics that trip up "
            "every new team.",
            "intermediate",
            139.0,
        ),
        (
            "Streaming Data with Kafka",
            "Topics, partitions, consumer groups and exactly-once semantics explained through a "
            "clickstream pipeline you build yourself. You will handle rebalances, lag and out-of-order "
            "events.",
            "advanced",
            169.0,
        ),
        (
            "SQL for Analytics: Window Functions and CTEs",
            "Move past GROUP BY into running totals, rankings, gaps-and-islands and recursive "
            "queries. Every exercise is a question an analyst is genuinely asked on the job.",
            "beginner",
            59.0,
        ),
        (
            "Dimensional Modelling and the Modern Warehouse",
            "Facts, dimensions, slowly changing types and grain selection, applied to a columnar "
            "warehouse. Learn why a well-chosen grain removes entire classes of reporting bug.",
            "intermediate",
            129.0,
        ),
        (
            "dbt: Analytics Engineering in Practice",
            "Turn SQL into a tested, version-controlled, documented transformation layer. Covers "
            "models, sources, snapshots, and the testing conventions that make a warehouse "
            "trustworthy.",
            "intermediate",
            119.0,
        ),
        (
            "Data Quality, Contracts and Observability",
            "Detect broken pipelines before your stakeholders do. Implement schema contracts, "
            "freshness and volume checks, and anomaly alerts that page a human only when they should.",
            "advanced",
            149.0,
        ),
        (
            "Apache Spark for Large-Scale Processing",
            "The execution model first — partitions, shuffles and lazy evaluation — then the tuning "
            "that follows from understanding it. You will diagnose skew and spill on a genuinely large "
            "dataset.",
            "advanced",
            179.0,
        ),
    ],
    "Cloud": [
        (
            "AWS Fundamentals for Developers",
            "The services you actually touch on day one: IAM, S3, EC2, RDS and VPC basics. Built "
            "around deploying a small application rather than memorising the service catalogue.",
            "beginner",
            89.0,
        ),
        (
            "Serverless Architecture with Lambda and API Gateway",
            "Event-driven design, cold starts, concurrency limits and idempotent handlers. Covers "
            "where serverless is genuinely cheaper and where it quietly becomes expensive.",
            "intermediate",
            129.0,
        ),
        (
            "Kubernetes on the Cloud",
            "Pods, services, ingress and the controller pattern, followed by autoscaling and resource "
            "requests that reflect real traffic. You will debug a CrashLoopBackOff from first "
            "principles.",
            "advanced",
            179.0,
        ),
        (
            "Terraform: Infrastructure as Code",
            "Declarative provisioning with modules, remote state and plan review as a team ritual. "
            "Includes importing existing infrastructure and surviving a state file conflict.",
            "intermediate",
            139.0,
        ),
        (
            "Cloud Cost Optimisation",
            "Attribute spend to teams, find idle capacity, and choose between reserved, spot and "
            "on-demand with numbers rather than instinct. A single afternoon of this usually pays for "
            "the course.",
            "intermediate",
            109.0,
        ),
        (
            "Google Cloud Data Services",
            "BigQuery, Dataflow, Pub/Sub and Cloud Storage as a working analytics stack. Emphasis on "
            "partitioning, clustering and query cost control.",
            "intermediate",
            129.0,
        ),
        (
            "Designing Multi-Region, Highly Available Systems",
            "Replication strategies, failover, consistency trade-offs and the failure domains people "
            "forget. You will write a runbook for a region outage and then test it.",
            "advanced",
            189.0,
        ),
    ],
    "Cybersecurity": [
        (
            "Web Application Security: The OWASP Top Ten",
            "Injection, broken access control, SSRF and the rest, demonstrated against a deliberately "
            "vulnerable application you run locally. Each lesson pairs the attack with the code change "
            "that closes it.",
            "beginner",
            89.0,
        ),
        (
            "Threat Modelling for Engineering Teams",
            "Run a STRIDE session on your own architecture and leave with a ranked, actionable risk "
            "list. Designed for teams who need security thinking during design rather than after "
            "launch.",
            "intermediate",
            119.0,
        ),
        (
            "Applied Cryptography for Developers",
            "Use primitives correctly without inventing your own: authenticated encryption, key "
            "derivation, signing and secure random. Focused on the handful of mistakes that account "
            "for most real-world breaks.",
            "advanced",
            159.0,
        ),
        (
            "Identity, OAuth 2.0 and OpenID Connect",
            "Flows, tokens, scopes and session handling explained without hand-waving. You implement "
            "an authorisation code flow with PKCE and then attack your own implementation.",
            "intermediate",
            129.0,
        ),
        (
            "Penetration Testing Fundamentals",
            "Reconnaissance, enumeration, exploitation and reporting, practised entirely within a "
            "provided lab environment. Covers scoping and rules of engagement so the work stays "
            "authorised and defensible.",
            "intermediate",
            139.0,
        ),
        (
            "Cloud Security Posture and IAM Hardening",
            "Least privilege at scale: policy analysis, permission boundaries and detecting drift "
            "across accounts. Includes auditing a messy production estate without breaking it.",
            "advanced",
            169.0,
        ),
        (
            "Incident Response and Digital Forensics",
            "Contain, investigate and recover from a live intrusion using timeline reconstruction and "
            "log correlation. Ends with writing the post-incident review that prevents a repeat.",
            "advanced",
            179.0,
        ),
    ],
    "Web Development": [
        (
            "Modern JavaScript in Practice",
            "Modules, async patterns, destructuring and the parts of the language that changed after "
            "ES6. Assumes you can already write a for-loop and nothing more.",
            "beginner",
            69.0,
        ),
        (
            "Building APIs with FastAPI",
            "Typed request and response models, dependency injection, background tasks and "
            "authentication. You ship a documented API with tests rather than a toy endpoint.",
            "intermediate",
            109.0,
        ),
        (
            "React from Fundamentals to Production",
            "Components, state, effects and data fetching, followed by the render-performance work "
            "that separates a demo from a product. Includes testing and accessible component "
            "patterns.",
            "intermediate",
            139.0,
        ),
        (
            "CSS Layout: Flexbox, Grid and Responsive Design",
            "Stop fighting the layout engine. Build real interfaces with grid and flexbox, then make "
            "them adapt across viewports without a pile of media queries.",
            "beginner",
            59.0,
        ),
        (
            "Full-Stack TypeScript",
            "Share types across client and server, model domain state precisely, and use the compiler "
            "as a design tool. Covers generics, discriminated unions and the escape hatches worth "
            "knowing.",
            "advanced",
            159.0,
        ),
        (
            "Web Performance: Core Web Vitals",
            "Measure and fix largest contentful paint, layout shift and interaction latency on a real "
            "site. Profiling comes first, because most performance work targets the wrong "
            "bottleneck.",
            "intermediate",
            119.0,
        ),
        (
            "Server-Side Rendering and Progressive Enhancement",
            "Deliver fast, accessible pages that work before JavaScript loads, then layer interactivity "
            "on top. Covers templating, caching and the hydration cost people underestimate.",
            "intermediate",
            99.0,
        ),
    ],
    "DevOps": [
        (
            "Docker for Developers",
            "Images, layers, volumes and networking, with a focus on small reproducible builds. You "
            "will containerise an existing application and cut its image size by more than half.",
            "beginner",
            79.0,
        ),
        (
            "CI/CD Pipelines with GitHub Actions",
            "Build, test and deploy on every push, with caching, matrix builds and environment "
            "protection rules. Includes securing secrets and reviewing what a third-party action can "
            "actually read.",
            "intermediate",
            109.0,
        ),
        (
            "Observability: Metrics, Logs and Traces",
            "Instrument a distributed system so that a production question has an answer. Covers "
            "structured logging, span propagation and dashboards that reflect user experience rather "
            "than CPU.",
            "advanced",
            149.0,
        ),
        (
            "Site Reliability Engineering Practices",
            "Service level objectives, error budgets, toil reduction and blameless post-mortems. "
            "Turns reliability from an argument into a measurable, negotiable budget.",
            "advanced",
            169.0,
        ),
        (
            "Git at Scale: Branching, Rebasing and Recovery",
            "Understand the object model, then use it to recover from any mess: lost commits, bad "
            "merges, rewritten history. Includes branching strategies that suit small teams shipping "
            "daily.",
            "beginner",
            49.0,
        ),
        (
            "Linux Systems Administration",
            "Processes, permissions, systemd, networking and disk management from the command line. "
            "Aimed at developers who keep hitting the limits of copy-pasted shell commands.",
            "beginner",
            89.0,
        ),
        (
            "Progressive Delivery: Feature Flags, Canaries and Blue-Green",
            "Decouple deploy from release so a rollback is a configuration change. Covers flag "
            "hygiene, automated canary analysis and cleaning up flags before they become permanent "
            "branches.",
            "intermediate",
            129.0,
        ),
    ],
    "Business": [
        (
            "Product Management for Technical Teams",
            "Discovery, prioritisation and roadmapping for people who can read the code. Covers "
            "writing problem statements that survive contact with engineering and saying no with "
            "evidence.",
            "beginner",
            99.0,
        ),
        (
            "Financial Modelling for Startup Founders",
            "Build a driver-based model covering runway, unit economics and hiring plans. You leave "
            "with a spreadsheet you can defend line by line in an investor meeting.",
            "intermediate",
            129.0,
        ),
        (
            "Pricing Strategy and Monetisation",
            "Value metrics, packaging, tier design and the mechanics of a price increase that does not "
            "cost you your base. Includes willingness-to-pay research you can run in a fortnight.",
            "intermediate",
            119.0,
        ),
        (
            "Growth Marketing and Funnel Analytics",
            "Instrument acquisition through retention, then run experiments that produce decisions "
            "rather than dashboards. Covers cohort analysis, attribution limits and sample sizing.",
            "intermediate",
            109.0,
        ),
        (
            "Negotiation for Engineers and Managers",
            "Preparation frameworks, interests versus positions, and handling deadlock without "
            "damaging the relationship. Practised on salary, vendor and cross-team scope "
            "conversations.",
            "beginner",
            79.0,
        ),
        (
            "Building and Leading Engineering Teams",
            "Hiring, feedback, performance conversations and organisational design as teams grow past "
            "the point where everyone can be in one room. Written for first-time and struggling "
            "managers alike.",
            "advanced",
            159.0,
        ),
        (
            "Go-to-Market Strategy for B2B SaaS",
            "Segment, position and build a repeatable sales motion for a technical product. Covers "
            "ideal customer profiles, pipeline maths and when founder-led selling has to end.",
            "advanced",
            149.0,
        ),
    ],
    "Design": [
        (
            "UX Research Methods",
            "Choose and run the right study: interviews, usability tests, diary studies and surveys. "
            "Emphasis on synthesis, so findings change the product instead of decorating a slide.",
            "beginner",
            89.0,
        ),
        (
            "Design Systems and Component Libraries",
            "Tokens, component APIs, documentation and the governance that stops a system fragmenting. "
            "Covers versioning and migrating consumers without freezing product work.",
            "intermediate",
            129.0,
        ),
        (
            "Interaction Design and Micro-Interactions",
            "Motion, feedback and state transitions that make an interface feel responsive and "
            "understood. Every principle is paired with a prototype you build and critique.",
            "intermediate",
            109.0,
        ),
        (
            "Accessibility: WCAG in Practice",
            "Semantic structure, keyboard operation, focus management and colour contrast, tested with "
            "real assistive technology. Accessible interfaces are better interfaces, and this course "
            "shows why.",
            "beginner",
            79.0,
        ),
        (
            "Information Architecture and Navigation",
            "Card sorting, tree testing and labelling for products that have outgrown their original "
            "structure. Teaches you to diagnose a navigation problem that looks like a search "
            "problem.",
            "intermediate",
            99.0,
        ),
        (
            "Data Visualisation Design Principles",
            "Encoding choices, colour, annotation and chart selection grounded in perception research. "
            "You will redesign three misleading charts and articulate exactly what was wrong.",
            "intermediate",
            119.0,
        ),
        (
            "Figma for Product Teams",
            "Auto layout, variants, shared libraries and handoff conventions that developers actually "
            "follow. Aimed at teams collaborating in one file without stepping on each other.",
            "beginner",
            69.0,
        ),
    ],
}


def seed_users(session: Session) -> list[str]:
    """Create the demo admin and learner accounts if they are missing."""
    messages: list[str] = []

    for email, password, role in (
        (ADMIN_EMAIL, ADMIN_PASSWORD, ROLE_ADMIN),
        (USER_EMAIL, USER_PASSWORD, ROLE_USER),
    ):
        existing = session.exec(select(User).where(User.email == email)).first()
        if existing is not None:
            messages.append(f"  {email} already exists ({existing.role})")
            continue

        # Validate through the same schema the registration form uses, so a demo
        # account can never be one the app itself would have rejected.
        credentials = RegisterRequest(email=email, password=password)
        session.add(
            User(
                email=credentials.email,
                password_hash=hash_password(credentials.password),
                role=role,
            )
        )
        session.commit()
        messages.append(f"  created {email} ({role})")

    return messages


def seed_products(session: Session) -> int:
    """Insert the catalog through product_service. Returns the number created."""
    created = 0
    for category, rows in CATALOG.items():
        for title, description, level, price in rows:
            product_service.create_product(
                session,
                ProductCreate(
                    title=title,
                    description=description,
                    category=category,
                    level=level,
                    price=price,
                ),
            )
            created += 1
    return created


def reset_products(session: Session) -> int:
    """Delete every product. Returns how many were removed."""
    products = session.exec(select(Product)).all()
    for product in products:
        session.delete(product)
    session.commit()
    return len(products)


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the SmartReco catalog.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete every existing product before seeding",
    )
    args = parser.parse_args()

    init_db()

    with Session(engine) as session:
        print("Users:")
        for message in seed_users(session):
            print(message)

        if args.reset:
            removed = reset_products(session)
            print(f"\nRemoved {removed} existing product(s).")

        existing = product_service.count_products(session)
        if existing:
            print(
                f"\nCatalog already holds {existing} product(s) — skipping. "
                "Re-run with --reset to rebuild it."
            )
            return 0

        created = seed_products(session)
        categories = len(CATALOG)

    print(f"\nSeeded {created} products across {categories} categories.")
    print("\nDemo accounts:")
    print(f"  admin   {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    print(f"  learner {USER_EMAIL} / {USER_PASSWORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
