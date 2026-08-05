"""All product reads and mutations. No route touches the products table directly.

This module is the single choke point named in CONTEXT §5, and the dual-write
invariant is enforced here: **SQL and Chroma commit together or not at all.**
The pattern in every mutation is the same —

    session.flush()   # take the primary key, hold the transaction open
    <vector sync>     # if this raises, roll back; never half-commit
    session.commit()
"""

import logging

from sqlmodel import Session, func, or_, select

from app.models import Product
from app.schemas.product import ProductCreate, ProductUpdate

logger = logging.getLogger(__name__)


class VectorSyncError(RuntimeError):
    """A product write was rolled back because its vector could not be synced."""


def _escape_like(term: str) -> str:
    """Neutralise LIKE wildcards so a user searching "100%" gets a literal match."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_products(
    session: Session,
    *,
    q: str | None = None,
    category: str | None = None,
) -> list[Product]:
    """Catalog listing with optional keyword search and category filter."""
    statement = select(Product)

    if q and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        statement = statement.where(
            or_(
                Product.title.ilike(pattern, escape="\\"),
                Product.description.ilike(pattern, escape="\\"),
            )
        )

    if category and category.strip():
        statement = statement.where(Product.category == category.strip())

    statement = statement.order_by(Product.category, Product.title)
    return list(session.exec(statement).all())


def list_categories(session: Session) -> list[str]:
    """Distinct categories present in the catalog, for the filter control."""
    statement = select(Product.category).distinct().order_by(Product.category)
    return list(session.exec(statement).all())


def get_product(session: Session, product_id: int) -> Product | None:
    """Fetch one product, or None if it does not exist."""
    return session.get(Product, product_id)


def count_products(session: Session) -> int:
    """Total catalog size. Used by the seed script to stay idempotent."""
    return session.exec(select(func.count()).select_from(Product)).one()


def _sync_upsert(session: Session, product: Product, *, operation: str) -> bool:
    """Embed and upsert one product into Chroma using active backend, or roll SQL write back."""
    from app.services.vector_store import vector_store

    try:
        vector_store.upsert_products([product])
    except Exception as exc:  # noqa: BLE001 — Mesh or Chroma, both are fatal here
        session.rollback()
        logger.error(
            "product_service.vector_sync_failed op=%s product_id=%s error=%s",
            operation,
            product.id,
            exc,
        )
        raise VectorSyncError(
            f"Vector sync failed for product {product.id}; the write was rolled back."
        ) from exc

    return True


def _sync_delete(session: Session, product_id: int) -> bool:
    """Remove one product's vector from Chroma, or roll SQL delete back."""
    from app.services.vector_store import vector_store

    try:
        vector_store.delete_product(product_id)
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.error(
            "product_service.vector_sync_failed op=delete product_id=%s error=%s",
            product_id,
            exc,
        )
        raise VectorSyncError(
            f"Vector delete failed for product {product_id}; the write was rolled back."
        ) from exc

    return True


def create_product(session: Session, data: ProductCreate) -> Product:
    """Insert a product, embed it, and commit both or neither."""
    product = Product(
        title=data.title,
        description=data.description,
        category=data.category,
        level=data.level,
        price=data.price,
    )
    session.add(product)
    session.flush()

    _sync_upsert(session, product, operation="create")

    session.commit()
    session.refresh(product)
    return product


def update_product(
    session: Session, product_id: int, data: ProductUpdate
) -> Product | None:
    """Update a product, re-embed it, and commit both or neither."""
    product = session.get(Product, product_id)
    if product is None:
        return None

    product.title = data.title
    product.description = data.description
    product.category = data.category
    product.level = data.level
    product.price = data.price

    session.add(product)
    session.flush()

    _sync_upsert(session, product, operation="update")

    session.commit()
    session.refresh(product)
    return product


def delete_product(session: Session, product_id: int) -> bool:
    """Delete a product, remove its vector, and commit both or neither."""
    product = session.get(Product, product_id)
    if product is None:
        return False

    session.delete(product)
    session.flush()

    _sync_delete(session, product_id)

    session.commit()
    return True
