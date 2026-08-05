"""The `users` table (docs/CONTEXT.md §5)."""

from datetime import datetime

from sqlalchemy import CheckConstraint
from sqlmodel import Field, SQLModel

from app.models.base import utc_now, utc_timestamp_column

ROLE_USER = "user"
ROLE_ADMIN = "admin"
ROLES = (ROLE_USER, ROLE_ADMIN)


class User(SQLModel, table=True):
    """An account. Auth is session cookie + bcrypt, so only the hash is stored."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'admin')",
            name="ck_users_role_valid",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True, max_length=255)
    password_hash: str = Field(max_length=255)
    role: str = Field(default=ROLE_USER, max_length=16)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=utc_timestamp_column(),
    )
