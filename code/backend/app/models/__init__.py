"""SQLModel tables.

Importing this package registers all six tables on `SQLModel.metadata`, which is
what `init_db()` creates. Import the package — not individual modules — anywhere
schema registration matters.
"""

from app.models.agent_run import (
    STATUS_DEGRADED,
    STATUS_FAILED,
    STATUS_OK,
    AgentRun,
)
from app.models.base import UTCDateTime, utc_now, utc_timestamp_column
from app.models.event import Event
from app.models.interest_profile import UserInterestProfile
from app.models.product import Product
from app.models.recommendation import Recommendation
from app.models.user import ROLE_ADMIN, ROLE_USER, ROLES, User

__all__ = [
    "ROLES",
    "ROLE_ADMIN",
    "ROLE_USER",
    "STATUS_DEGRADED",
    "STATUS_FAILED",
    "STATUS_OK",
    "AgentRun",
    "Event",
    "Product",
    "Recommendation",
    "UTCDateTime",
    "User",
    "UserInterestProfile",
    "utc_now",
    "utc_timestamp_column",
]
