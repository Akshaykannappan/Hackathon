"""Shared FastAPI dependencies: who is calling, and may they."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.security import SESSION_COOKIE_NAME, read_session
from app.models import ROLE_ADMIN, User

SessionDep = Annotated[Session, Depends(get_session)]


def get_current_user(request: Request, session: SessionDep) -> User | None:
    """Resolve the signed session cookie to a User, or None.

    Returns None rather than raising: most pages are public and simply render
    differently when signed out.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    user_id = read_session(token)
    if user_id is None:
        return None
    # A valid signature over a deleted account still means "logged out".
    return session.get(User, user_id)


CurrentUser = Annotated[User | None, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    """Gate admin routes. 403 for both anonymous and non-admin callers."""
    if user is None or user.role != ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required.",
        )
    return user


AdminUser = Annotated[User, Depends(require_admin)]
