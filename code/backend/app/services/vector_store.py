"""Chroma wrapper. The only module that talks to the vector store.

The dual-write invariant lives here as one line of policy: **the Chroma document
ID is the SQL product primary key, as a string** (CONTEXT §5). Nothing composes
an ID any other way, which is what makes `scripts/reindex_vectors.py` a genuine
recovery path rather than a guess.

Every embedding goes through `app/ai/mesh_client.py` (CONTEXT R1/R2). This
module never constructs an AI client of its own.
"""

import logging
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.ai.mesh_client import mesh_client
from app.core.config import BACKEND_DIR, settings
from app.models import Product

logger = logging.getLogger(__name__)


def document_id(product_id: int) -> str:
    """The one place a Chroma ID is derived. Always the SQL primary key."""
    return str(product_id)


def compose_document(product: Product) -> str:
    """The text that gets embedded: title, description and category.

    Category is included deliberately — it is the strongest single term for
    separating "Cloud" from "Cybersecurity" when their descriptions overlap.
    """
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
        # Same reasoning as the SQLite path: a relative directory must not depend
        # on the working directory uvicorn happened to be launched from.
        self.persist_dir = (
            raw_dir if str(raw_dir).startswith("/") else str(BACKEND_DIR / raw_dir)
        )
        self._client: Any = None
        self._collection: Any = None

    def _connect(self) -> Any:
        if self._client is None:
            self._client = chromadb.PersistentClient(
                path=self.persist_dir,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        return self._client

    @property
    def collection(self) -> Any:
        """The Chroma collection, opened on first use rather than at import."""
        if self._collection is None:
            self._collection = self._connect().get_or_create_collection(
                name=self.collection_name,
                # Cosine matches how the embeddings are normalised and makes the
                # distance→similarity conversion in `query` well defined.
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    # ------------------------------------------------------------------ writes

    def upsert_products(self, products: list[Product]) -> int:
        """Embed and upsert products in one batched Mesh call. Returns the count.

        Raises `MeshUnavailableError` if embedding fails — the caller decides
        whether that means rolling back a SQL write or aborting a reindex.
        """
        if not products:
            return 0

        documents = [compose_document(product) for product in products]
        vectors = mesh_client.embed(documents)

        self.collection.upsert(
            ids=[document_id(product.id) for product in products],
            embeddings=vectors,
            documents=documents,
            metadatas=[product_metadata(product) for product in products],
        )
        return len(products)

    def delete_product(self, product_id: int) -> None:
        """Remove one product's document. Deleting a missing ID is not an error."""
        self.collection.delete(ids=[document_id(product_id)])

    def reset(self) -> None:
        """Drop and recreate the collection — the reindex script's clean slate."""
        client = self._connect()
        try:
            client.delete_collection(self.collection_name)
        except Exception:  # noqa: BLE001 — Chroma raises a bare error when absent
            logger.info(
                "vector_store.collection_absent name=%s", self.collection_name
            )
        self._collection = None

    # ------------------------------------------------------------------- reads

    def query(
        self, query_texts: list[str], *, top_k: int
    ) -> list[list[dict[str, Any]]]:
        """Multi-query search. Returns one result list per query, in order.

        All queries are embedded in a single batched Mesh call. Cosine distance
        is converted to a similarity in [0, 1] so that both retrievers speak the
        same units and one threshold means the same thing for either.
        """
        if not query_texts:
            return []

        vectors = mesh_client.embed(query_texts)
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
        """How many documents the collection holds — used to detect drift."""
        return self.collection.count()


vector_store = VectorStore()
