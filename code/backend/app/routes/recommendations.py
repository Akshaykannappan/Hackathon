"""Legacy dashboard alias.

The dashboard is gone as a separate page — its recommendation message,
recommended cards and "how this was built" summary all render on the catalog,
which is now the home page (`app/routes/catalog.py`). This redirect exists so
no bookmark, link or demo script breaks.
"""

from fastapi import APIRouter
from starlette.responses import RedirectResponse, Response

router = APIRouter(tags=["recommendations"])


@router.get("/dashboard")
def dashboard() -> Response:
    """Everything the dashboard showed now lives on the home page."""
    return RedirectResponse("/", status_code=307)
