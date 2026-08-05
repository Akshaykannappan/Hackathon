"""Pydantic request/response bodies. One module per domain area."""

from app.schemas.auth import LoginRequest, RegisterRequest
from app.schemas.event import EVENT_TYPES, MAX_BATCH_SIZE, EventBatch, EventIn
from app.schemas.product import LEVELS, ProductCreate, ProductUpdate

__all__ = [
    "EVENT_TYPES",
    "LEVELS",
    "MAX_BATCH_SIZE",
    "EventBatch",
    "EventIn",
    "LoginRequest",
    "ProductCreate",
    "ProductUpdate",
    "RegisterRequest",
]
