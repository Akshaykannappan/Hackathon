#!/usr/bin/env python3
"""Mesh API verification script.

Verifies:
1. MESH_API_KEY format validation (must start with 'rsk_')
2. Model discovery listing embedding models with id, is_free, and pricing
3. Single chat completion round-trip
4. Batched embedding creation with 3 strings
"""

import sys
from pathlib import Path

# Add code/backend directory to sys.path so app module can be imported
backend_path = Path(__file__).resolve().parent.parent / "code" / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from app.core.config import settings
from app.ai.mesh_client import mesh_client


def main():
    api_key = getattr(settings, "mesh_api_key", None) or getattr(settings, "MESH_API_KEY", None)

    if not api_key:
        print("ERROR: MESH_API_KEY is missing from configuration / environment.", file=sys.stderr)
        sys.exit(1)

    if not isinstance(api_key, str) or not api_key.startswith("rsk_"):
        print("ERROR: MESH_API_KEY is invalid (must start with 'rsk_').", file=sys.stderr)
        sys.exit(1)

    print("1. MESH_API_KEY format verified.")

    # 2. Fetch and print embedding models
    print("\n2. Fetching embedding models from Mesh API...")
    try:
        models = mesh_client.list_embedding_models()
    except Exception as err:
        print(f"ERROR listing embedding models: {err}", file=sys.stderr)
        sys.exit(1)

    if not models:
        print("ERROR: No embedding models returned by Mesh API.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(models)} embedding model(s):")
    for m in models:
        model_id = m.get("id", "unknown")
        is_free = m.get("is_free", "unknown")
        pricing = m.get("pricing") or m.get("pricing_per_1k") or "N/A"
        print(f"  - Model ID: {model_id} | Free: {is_free} | Pricing: {pricing}")

    # 3. Chat round-trip
    print("\n3. Testing chat completion...")
    try:
        messages = [{"role": "user", "content": "Respond with: Mesh chat test successful."}]
        reply = mesh_client.chat(messages)
        if not reply:
            print("ERROR: Chat completion returned an empty response.", file=sys.stderr)
            sys.exit(1)
        print(f"Chat reply: {reply.strip()}")
    except Exception as err:
        print(f"ERROR during chat completion: {err}", file=sys.stderr)
        sys.exit(1)

    # 4. Batched embed with 3 strings
    print("\n4. Testing batched embeddings with 3 strings...")
    test_strings = [
        "First test string for embedding verification.",
        "Second test string with distinct content.",
        "Third test string for batch dimension validation.",
    ]
    try:
        vectors = mesh_client.embed(test_strings)
        if not vectors or len(vectors) != len(test_strings):
            print(
                f"ERROR: Expected {len(test_strings)} vectors, got {len(vectors) if vectors else 0}.",
                file=sys.stderr,
            )
            sys.exit(1)

        vector_count = len(vectors)
        vector_dim = len(vectors[0])
        print(
            f"Batched embedding successful: vector count = {vector_count}, "
            f"dimension of first vector = {vector_dim}"
        )
    except Exception as err:
        print(f"ERROR during batched embedding: {err}", file=sys.stderr)
        sys.exit(1)

    print("\nAll Mesh API verification checks passed successfully!")


if __name__ == "__main__":
    main()
