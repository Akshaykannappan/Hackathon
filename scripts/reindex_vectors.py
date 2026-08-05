#!/usr/bin/env python3
"""Rebuild Chroma vector collection from SQL products table.

Drift recovery path (architecture §4). Works with both Mesh and local embeddings.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "code" / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from sqlmodel import Session, select

from app.core.database import engine
from app.models import Product
from app.services.vector_store import vector_store


def reindex():
    backend = vector_store.get_active_backend()
    print(f"Active vector embedding backend: {backend.upper()}")

    with Session(engine) as session:
        products = list(session.exec(select(Product)).all())
        print(f"Found {len(products)} product(s) in SQL database.")

        print("Resetting Chroma collection...")
        vector_store.reset()

        print(f"Upserting {len(products)} vector embeddings using {backend} backend...")
        count = vector_store.upsert_products(products)
        print(f"Successfully reindexed {count} products in Chroma vector store.")


if __name__ == "__main__":
    reindex()
