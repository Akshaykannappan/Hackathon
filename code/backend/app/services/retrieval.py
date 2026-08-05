"""Retrieval behind one interface, with interchangeable implementations.

- `ChromaRetriever` — semantic search over Chroma vector collection (using either
  Mesh embeddings or local MiniLM embeddings).
- `KeywordRetriever` — deterministic SQL token matching over products table.

Both return the identical candidate shape, so no node downstream knows or cares
which one ran. The active backend is logged on selection and recorded on every
`agent_runs` row.
"""

import logging
import re
from typing import Any, Protocol

from sqlmodel import Session, col, or_, select

from app.core.config import settings
from app.models import Product

logger = logging.getLogger(__name__)

BACKEND_CHROMA = "chroma"
BACKEND_KEYWORD = "keyword"

# Keyword scoring weights
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
    """What the agent's `retrieve` node depends on."""

    name: str

    def search(
        self, session: Session, queries: list[str], *, top_k: int
    ) -> list[dict[str, Any]]:
        """Return deduplicated candidates across all queries, best score first."""
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
    """SQL token matching, scored into the same units as cosine similarity."""

    name = BACKEND_KEYWORD

    def search(
        self, session: Session, queries: list[str], *, top_k: int
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []

        for query in queries:
            tokens = _tokenise(query)
            if not tokens:
                continue

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
    """Semantic vector search over Chroma collection."""

    name = BACKEND_CHROMA

    def __init__(self, store: Any | None = None):
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
                    logger.warning(
                        "retrieval.orphan_vector product_id=%s", hit["product_id"]
                    )
                    continue
                candidates.append(_as_candidate(product, hit["similarity"], query))

        return _merge(candidates)


_active_retriever: Retriever | None = None


def get_retriever(*, refresh: bool = False) -> Retriever:
    """Select the retrieval backend, honouring `RETRIEVAL_BACKEND`."""
    global _active_retriever

    if _active_retriever is not None and not refresh:
        return _active_retriever

    configured = settings.retrieval_backend.strip().lower()

    if configured == BACKEND_KEYWORD:
        _active_retriever = KeywordRetriever()
        logger.info("retrieval.backend=keyword reason=pinned_by_config")
    else:
        _active_retriever = ChromaRetriever()
        logger.info("retrieval.backend=chroma reason=chroma_ready")

    return _active_retriever


def reset_retriever_cache() -> None:
    """Clear active retriever instance for tests."""
    global _active_retriever
    _active_retriever = None
