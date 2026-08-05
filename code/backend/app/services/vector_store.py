"""Chroma wrapper. The only module that talks to the vector store.

The dual-write invariant lives here as one line of policy: **the Chroma document
ID is the SQL product primary key, as a string** (CONTEXT §5). Nothing composes
an ID any other way, which is what makes `scripts/reindex_vectors.py` a genuine
recovery path rather than a guess.

Supports two embedding sources selected by `settings.embedding_backend`:
  - "mesh"  → mesh_client.embed (preferred, used when balance exists)
  - "local" → Chroma's bundled default embedding function (384-dim MiniLM ONNX)
  - "auto"  → probes Mesh once, falls back to local, and logs which is active.
"""

import logging
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.utils import embedding_functions

from app.ai.mesh_client import MeshUnavailableError, mesh_client
from app.core.config import BACKEND_DIR, settings
from app.models import Product

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton for the local ONNX embedding function.
#
# The DefaultEmbeddingFunction downloads and initialises the all-MiniLM-L6-v2
# ONNX model once per process.  If this were created inside VectorStore or per
# query call it would re-load the model on every fresh VectorStore instance
# (e.g. in tests, or on the first real request in a new process), paying
# 100-3,000ms each time.  Holding one instance here means every VectorStore
# shares the same already-loaded model.
# ---------------------------------------------------------------------------
_LOCAL_EF: Any = None


def _get_local_ef() -> Any:
    """Return the process-level MiniLM embedding function, initialising once."""
    global _LOCAL_EF
    if _LOCAL_EF is None:
        _LOCAL_EF = embedding_functions.DefaultEmbeddingFunction()
        logger.info("vector_store.local_ef_loaded model=all-MiniLM-L6-v2")
    return _LOCAL_EF


def document_id(product_id: int) -> str:
    """The one place a Chroma ID is derived. Always the SQL primary key."""
    return str(product_id)


def compose_document(product: Product) -> str:
    """The text that gets embedded: title, description and category."""
    return f"{product.title}\n\n{product.description}\n\nCategory: {product.category}"


def product_metadata(product: Product) -> dict[str, Any]:
    """Metadata kept alongside the vector, for filtered search."""
    return {
        "category": product.category,
        "level": product.level,
        "price": float(product.price),
        "updated_at": product.updated_at.isoformat(),
    }


class VectorStore:
    """A persistent Chroma collection holding one document per catalog product."""

    def __init__(
        self, collection_name: str | None = None, persist_dir: str | None = None
    ):
        self.collection_name = collection_name or settings.chroma_collection
        raw_dir = persist_dir or settings.chroma_persist_dir
        self.persist_dir = (
            raw_dir if str(raw_dir).startswith("/") else str(BACKEND_DIR / raw_dir)
        )
        self._client: Any = None
        self._collection: Any = None
        self._active_backend: str | None = None

    def get_active_backend(self) -> str:
        """Probe Mesh once if 'auto', or return configured embedding backend ('mesh' or 'local')."""
        if self._active_backend is not None:
            return self._active_backend

        configured = getattr(settings, "embedding_backend", "auto").strip().lower()

        if configured == "mesh":
            self._active_backend = "mesh"
            logger.info("vector_store.backend_selected backend=mesh reason=configured")
            return "mesh"

        if configured == "local":
            self._active_backend = "local"
            logger.info("vector_store.backend_selected backend=local reason=configured")
            return "local"

        # "auto" mode: probe Mesh once
        if not settings.mesh_api_key:
            self._active_backend = "local"
            logger.info("vector_store.backend_selected backend=local reason=no_api_key")
            return "local"

        try:
            vectors = mesh_client.embed(["smartreco embedding capability probe"])
            if vectors and len(vectors[0]) > 0:
                self._active_backend = "mesh"
                logger.info("vector_store.backend_selected backend=mesh reason=probe_successful")
                return "mesh"
        except (MeshUnavailableError, Exception) as exc:
            logger.info(
                "vector_store.backend_selected backend=local reason=mesh_probe_failed error=%s",
                exc,
            )

        self._active_backend = "local"
        return "local"

    def warm(self) -> None:
        """Pre-warm the embedding function so the first query pays no load cost.

        Called at application startup (lifespan).  When the local backend is
        active this forces the ONNX model to load and JIT-compile now rather
        than on the first real user request.
        """
        backend = self.get_active_backend()
        if backend == "local":
            ef = _get_local_ef()
            # One minimal embed call drives the ONNX session initialisation.
            ef(["warmup"])
            logger.info("vector_store.warmed backend=local")

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of text strings using the active embedding backend."""
        backend = self.get_active_backend()
        if backend == "mesh":
            return mesh_client.embed(texts)

        return _get_local_ef()(texts)

    def _connect(self) -> Any:
        if self._client is None:
            self._client = chromadb.PersistentClient(
                path=self.persist_dir,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        return self._client

    @property
    def collection(self) -> Any:
        """The Chroma collection, opened on first use.

        If stored metadata's embedding_backend does not match active_backend,
        recreate the collection to prevent mixing incompatible vector spaces.
        """
        active_backend = self.get_active_backend()

        if self._collection is None:
            client = self._connect()
            col = None
            try:
                existing = client.get_collection(name=self.collection_name)
                meta = existing.metadata or {}
                stored_backend = meta.get("embedding_backend")
                if stored_backend != active_backend:
                    logger.warning(
                        "vector_store.backend_mismatch stored=%s active=%s resetting_collection",
                        stored_backend,
                        active_backend,
                    )
                    client.delete_collection(self.collection_name)
                else:
                    col = existing
            except Exception:
                col = None

            if col is None:
                col = client.create_collection(
                    name=self.collection_name,
                    metadata={
                        "hnsw:space": "cosine",
                        "embedding_backend": active_backend,
                    },
                )
            self._collection = col

        return self._collection

    # ------------------------------------------------------------------ writes

    def upsert_products(self, products: list[Product]) -> int:
        """Embed and upsert products in Chroma using whichever backend is active."""
        if not products:
            return 0

        documents = [compose_document(product) for product in products]
        vectors = self.embed_texts(documents)

        self.collection.upsert(
            ids=[document_id(product.id) for product in products],
            embeddings=vectors,
            documents=documents,
            metadatas=[product_metadata(product) for product in products],
        )
        return len(products)

    def delete_product(self, product_id: int) -> None:
        """Remove one product's document."""
        self.collection.delete(ids=[document_id(product_id)])

    def reset(self) -> None:
        """Drop and recreate the collection — the reindex script's clean slate."""
        client = self._connect()
        try:
            client.delete_collection(self.collection_name)
        except Exception:
            logger.info("vector_store.collection_absent name=%s", self.collection_name)
        self._collection = None
        self._active_backend = None

    # ------------------------------------------------------------------- reads

    def query(
        self, query_texts: list[str], *, top_k: int
    ) -> list[list[dict[str, Any]]]:
        """Multi-query search returning candidate hits with similarity scores in [0, 1]."""
        if not query_texts:
            return []

        vectors = self.embed_texts(query_texts)
        response = self.collection.query(
            query_embeddings=vectors,
            n_results=top_k,
            include=["metadatas", "distances"],
        )

        results: list[list[dict[str, Any]]] = []
        for index in range(len(query_texts)):
            results.append(
                [
                    {
                        "product_id": int(doc_id),
                        "similarity": max(0.0, 1.0 - float(distance)),
                        "metadata": metadata,
                    }
                    for doc_id, distance, metadata in zip(
                        response["ids"][index],
                        response["distances"][index],
                        response["metadatas"][index],
                    )
                ]
            )
        return results

    def count(self) -> int:
        """How many documents the collection holds."""
        return self.collection.count()


vector_store = VectorStore()

__all__ = [
    "VectorStore",
    "compose_document",
    "document_id",
    "product_metadata",
    "vector_store",
]
