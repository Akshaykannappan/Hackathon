"""The single Jinja2 environment, and the frontend paths it renders from.

Resolved absolutely from this file's location for the same reason `.env` is:
the working directory a judge launches uvicorn from is not something we control.
"""

from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse

from app.core.config import BACKEND_DIR
from app.models import User

FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
TEMPLATES_DIR = FRONTEND_DIR / "templates"
STATIC_DIR = FRONTEND_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def render(
    request: Request,
    template: str,
    *,
    user: User | None = None,
    status_code: int = 200,
    **context: Any,
) -> HTMLResponse:
    """Render a page with the context every template expects.

    `user` reaches the navbar on every page, so routes never have to remember
    to pass it.
    """
    return templates.TemplateResponse(
        request,
        template,
        {"user": user, **context},
        status_code=status_code,
    )
