"""Registration, login, logout — server-rendered forms, not a JSON API."""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from starlette.responses import RedirectResponse, Response

from app.core.dependencies import CurrentUser, SessionDep
from app.core.security import (
    clear_session_cookie,
    hash_password,
    set_session_cookie,
    verify_password,
)
from app.core.templates import render
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest

router = APIRouter(tags=["auth"])

CATALOG_URL = "/catalog"


def _first_error(exc: ValidationError) -> str:
    """Turn a pydantic error into one line a person can act on."""
    message = exc.errors()[0]["msg"]
    # pydantic prefixes messages raised from custom validators.
    return message.removeprefix("Value error, ")


def _redirect_signed_in(user_id: int) -> RedirectResponse:
    """303 so the browser follows a POST with a GET."""
    response = RedirectResponse(CATALOG_URL, status_code=303)
    set_session_cookie(response, user_id)
    return response


@router.get("/register")
def register_form(request: Request, user: CurrentUser) -> Response:
    if user is not None:
        return RedirectResponse(CATALOG_URL, status_code=303)
    return render(request, "pages/register.html", user=user)


@router.post("/register")
def register(
    request: Request,
    session: SessionDep,
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
) -> Response:
    try:
        data = RegisterRequest(email=email, password=password)
    except ValidationError as exc:
        return render(
            request,
            "pages/register.html",
            error=_first_error(exc),
            email=email,
            status_code=400,
        )

    if session.exec(select(User).where(User.email == data.email)).first():
        return render(
            request,
            "pages/register.html",
            error="An account with that email already exists.",
            email=data.email,
            status_code=400,
        )

    user = User(email=data.email, password_hash=hash_password(data.password))
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        # Two registrations for the same address raced past the check above.
        session.rollback()
        return render(
            request,
            "pages/register.html",
            error="An account with that email already exists.",
            email=data.email,
            status_code=400,
        )
    session.refresh(user)

    return _redirect_signed_in(user.id)


@router.get("/login")
def login_form(request: Request, user: CurrentUser) -> Response:
    if user is not None:
        return RedirectResponse(CATALOG_URL, status_code=303)
    return render(request, "pages/login.html", user=user)


@router.post("/login")
def login(
    request: Request,
    session: SessionDep,
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
) -> Response:
    # One message for every failure mode — a bad address and a bad password must
    # be indistinguishable, or the form becomes an account-enumeration oracle.
    invalid = "Invalid email or password."

    try:
        data = LoginRequest(email=email, password=password)
    except ValidationError:
        return render(
            request,
            "pages/login.html",
            error=invalid,
            email=email,
            status_code=400,
        )

    user = session.exec(select(User).where(User.email == data.email)).first()
    if user is None or not verify_password(data.password, user.password_hash):
        return render(
            request,
            "pages/login.html",
            error=invalid,
            email=data.email,
            status_code=400,
        )

    return _redirect_signed_in(user.id)


@router.post("/logout")
def logout() -> Response:
    response = RedirectResponse(CATALOG_URL, status_code=303)
    clear_session_cookie(response)
    return response
