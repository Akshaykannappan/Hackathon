"""Shared column primitives for the SQLModel tables.

Not a table itself — this module exists so every model uses the *same*
timestamp semantics (docs/CONTEXT.md §8: all timestamps UTC, timezone-aware).
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, TypeDecorator


def utc_now() -> datetime:
    """Default factory for every timestamp column in the project.

    Use this instead of `datetime.utcnow`, which returns a naive value.
    """
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """A DateTime that always round-trips as timezone-aware UTC.

    SQLite has no native timezone support: the SQLAlchemy SQLite dialect drops
    the offset on write and hands back naive values on read. This decorator
    normalises to UTC on the way in and re-attaches `timezone.utc` on the way
    out, so a `created_at` read from the database is aware on SQLite exactly as
    it is on Postgres. Swapping `DATABASE_URL` stays a no-code-change operation.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: object
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(
        self, value: datetime | None, dialect: object
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def utc_timestamp_column(
    *,
    name: str | None = None,
    index: bool = False,
    nullable: bool = False,
    touch_on_update: bool = False,
) -> Column:
    """Build a fresh UTC timestamp Column.

    A Column instance belongs to exactly one table, so this must be called per
    field rather than shared as a module-level constant.

    `touch_on_update` sets a SQL-level `onupdate`, used by `products.updated_at`.
    """
    args: list[object] = [name] if name else []
    return Column(
        *args,
        UTCDateTime,
        index=index,
        nullable=nullable,
        onupdate=utc_now if touch_on_update else None,
    )
