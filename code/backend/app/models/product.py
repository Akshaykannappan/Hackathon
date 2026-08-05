"""The `products` table (docs/CONTEXT.md §5)."""

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import utc_now, utc_timestamp_column


class Product(SQLModel, table=True):
    """A catalog course.

    The primary key is also the Chroma document ID, as a string — see the
    dual-write invariant in docs/CONTEXT.md §5.
    """

    __tablename__ = "products"

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(max_length=255)
    description: str
    category: str = Field(index=True, max_length=100)
    level: str = Field(max_length=50)
    price: float = Field(default=0.0)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=utc_timestamp_column(),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=utc_timestamp_column(touch_on_update=True),
    )
