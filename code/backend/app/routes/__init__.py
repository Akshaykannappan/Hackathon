"""HTTP routers. Thin by design — business logic lives in `app/services`."""

from app.routes import admin, auth, catalog, events, intelligence, recommendations

__all__ = ["admin", "auth", "catalog", "events", "intelligence", "recommendations"]
