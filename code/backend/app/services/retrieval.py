"""Retrieval behind one interface, with two interchangeable implementations.

**Why two.** Mesh chat works on the free `minimax/m2-her` model, but the
embeddings endpoint requires account balance this project does not yet have
(`docs/phases/phase-01-foundation.md`). Rather than block the whole agent on a
billing problem, retrieval sits behind a protocol:

- `ChromaRetriever` — the real one. Semantic search over Mesh embeddings. It is
  written, wired and selected automatically the moment embeddings answer.
- `KeywordRetriever` — a documented temporary fallback. Deterministic SQL token
  matching over the products table, scored into the same [0, 1] similarity
  range so a single threshold means the same thing either way.

Both return the identical candidate shape, so no node downstream knows or cares
which one ran. The active backend is logged on selection and recorded on every
`agent_runs` row.

This is a fallback, not a stub: the keyword path is fully implemented and is
what actually runs today. See `docs/phases/phase-05-agent.md`.
"""

import logging
import re
from typing import Any, Protocol

from sqlmodel import Session, col, or_, select

from app.ai.mesh_client import MeshUnavailableError, mesh_client
from app.core.config import settings
from app.models import Product

logger = logging.getLogger(__name__)

BACKEND_CHROMA = "chroma"
BACKEND_KEYWORD = "keyword"

# Keyword scoring weights. A term in the title is worth more than the same term
# buried in a description.
_TITLE_WEIGHT = 2.0
_CATEGORY_WEIGHT = 1.5
_DESCRIPTION_WEIGHT = 1.0

_MIN_TOKEN_LENGTH = 2
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "for", "the", "with", "from", "into", "to", "of",
        "in", "on", "or", "how", "what", "why", "course", "courses",
    }
)


class Retriever(Protocol):
    """What the agent's `retrieve` node depends on. Nothing more."""

    name: str

    def search(
        self, session: Session, queries: list[str], *, top_k: int
    ) -> list[dict[str, Any]]:
        """Return deduplicated candidates across all queries, best score first.

        Each candidate is:
            {id, title, description, category, level, price, similarity, query}
        """
        ...


def _tokenise(text: str) -> list[str]:
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= _MIN_TOKEN_LENGTH and token not in _STOPWORDS
    ]
    return list(dict.fromkeys(tokens))


def _as_candidate(
    product: Product, similarity: float, query: str
) -> dict[str, Any]:
    """The one candidate shape. Both retrievers build it here."""
    return {
        "id": product.id,
        "title": product.title,
        "description": product.description,
        "category": product.category,
        "level": product.level,
        "price": float(product.price),
        "similarity": round(float(similarity), 4),
        "query": query,
    }


def _merge(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate by product id, keeping the strongest match for each."""
    best: dict[int, dict[str, Any]] = {}
    for candidate in candidates:
        existing = best.get(candidate["id"])
        if existing is None or candidate["similarity"] > existing["similarity"]:
            best[candidate["id"]] = candidate
    return sorted(best.values(), key=lambda c: c["similarity"], reverse=True)


class KeywordRetriever:
    """SQL token matching, scored into the same units as cosine similarity.

    Temporary. Deterministic, needs no network, and keeps the whole agent
    exercisable while the embeddings endpoint is unavailable.
    """

    name = BACKEND_KEYWORD

    def search(
        self, session: Session, queries: list[str], *, top_k: int
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []

        for query in queries:
            tokens = _tokenise(query)
            if not tokens:
                continue

            # Narrow in SQL, score in Python. The scoring needs per-field
            # attribution, which a LIKE cannot express.
            clauses = []
            for token in tokens:
                pattern = f"%{token}%"
                clauses.extend(
                    [
                        col(Product.title).ilike(pattern),
                        col(Product.description).ilike(pattern),
                        col(Product.category).ilike(pattern),
                    ]
                )
            rows = session.exec(select(Product).where(or_(*clauses))).all()

            best_possible = _TITLE_WEIGHT * len(tokens)
            for product in rows:
                title = product.title.lower()
                description = product.description.lower()
                category = product.category.lower()

                score = 0.0
                for token in tokens:
                    if token in title:
                        score += _TITLE_WEIGHT
                    elif token in category:
                        score += _CATEGORY_WEIGHT
                    elif token in description:
                        score += _DESCRIPTION_WEIGHT

                if score > 0:
                    candidates.append(
                        _as_candidate(product, min(score / best_possible, 1.0), query)
                    )

        return _merge(candidates)[: top_k * max(len(queries), 1)]


class ChromaRetriever:
    """Semantic search over Mesh embeddings — the intended production path.

    Hydrates every hit from SQL rather than from Chroma metadata, so the
    candidate shape is identical to the keyword retriever's and the SQL row
    stays the single source of truth for title and description.
    """

    name = BACKEND_CHROMA

    def __init__(self, store: Any | None = None):
        # Imported lazily: loading chromadb costs real time, and the keyword
        # path must not pay it.
        if store is None:
            from app.services.vector_store import vector_store

            store = vector_store
        self.store = store

    def search(
        self, session: Session, queries: list[str], *, top_k: int
    ) -> list[dict[str, Any]]:
        if not queries:
            return []

        per_query_hits = self.store.query(queries, top_k=top_k)

        wanted = {
            hit["product_id"] for hits in per_query_hits for hit in hits
        }
        if not wanted:
            return []

        products = {
            product.id: product
            for product in session.exec(
                select(Product).where(col(Product.id).in_(wanted))
            ).all()
        }

        candidates: list[dict[str, Any]] = []
        for query, hits in zip(queries, per_query_hits):
            for hit in hits:
                product = products.get(hit["product_id"])
                if product is None:
                    # In Chroma but not in SQL: drift. The SQL row is
                    # authoritative, so the orphan is ignored and
                    # scripts/reindex_vectors.py is the fix.
                    logger.warning(
                        "retrieval.orphan_vector product_id=%s", hit["product_id"]
                    )
                    continue
                candidates.append(_as_candidate(product, hit["similarity"], query))

        return _merge(candidates)


_embeddings_available: bool | None = None
_active_retriever: Retriever | None = None


def embeddings_available(*, refresh: bool = False) -> bool:
    """Whether Mesh will actually serve an embedding, probed once per process.

    A missing API key is answered without a network call. Otherwise one tiny
    embedding is attempted; `MeshUnavailableError` after the client's own
    retries means the endpoint is unusable — today, for want of balance.
    """
    global _embeddings_available

    if _embeddings_available is not None and not refresh:
        return _embeddings_available

    if not settings.mesh_api_key:
        _embeddings_available = False
        logger.warning("retrieval.embeddings_unavailable reason=no_api_key")
        return _embeddings_available

    try:
        vectors = mesh_client.embed(["smartreco embedding capability probe"])
        _embeddings_available = bool(vectors and vectors[0])
    except MeshUnavailableError as exc:
        _embeddings_available = False
        logger.warning("retrieval.embeddings_unavailable reason=%s", exc)

    return _embeddings_available


def get_retriever(*, refresh: bool = False) -> Retriever:
    """Select the retrieval backend, honouring `RETRIEVAL_BACKEND`.

    "chroma" and "keyword" pin a backend. "auto" probes for embeddings and
    falls back. The choice is made once per process and logged loudly, because
    which backend answered changes how a recommendation should be read.
    """
    global _active_retriever

    if _active_retriever is not None and not refresh:
        return _active_retriever

    configured = settings.retrieval_backend.strip().lower()

    if configured == BACKEND_KEYWORD:
        _active_retriever = KeywordRetriever()
        logger.info("retrieval.backend=keyword reason=pinned_by_config")
    elif configured == BACKEND_CHROMA:
        _active_retriever = ChromaRetriever()
        logger.info("retrieval.backend=chroma reason=pinned_by_config")
    elif embeddings_available(refresh=refresh):
        _active_retriever = ChromaRetriever()
        logger.info("retrieval.backend=chroma reason=embeddings_available")
    else:
        _active_retriever = KeywordRetriever()
        logger.warning(
            "retrieval.backend=keyword reason=embeddings_unavailable "
            "note=temporary_fallback_see_phase_05"
        )

    return _active_retriever


def reset_retriever_cache() -> None:
    """Clear the probe and selection. For tests and for `--refresh` tooling."""
    global _active_retriever, _embeddings_available
    _active_retriever = None
    _embeddings_available = None
