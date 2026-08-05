"""Admin product CRUD. Every route is gated by `require_admin`.

Routes here do HTTP shape and validation only — every mutation goes through
`product_service`, which is where the Phase 3 Chroma dual-write lands.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, Request, status
from pydantic import ValidationError
from starlette.responses import RedirectResponse, Response

from app.core.dependencies import AdminUser, SessionDep
from app.core.templates import render
from app.models import User
from app.schemas.product import LEVELS, ProductCreate, ProductUpdate
from app.services import product_service

router = APIRouter(prefix="/admin", tags=["admin"])

PRODUCTS_URL = "/admin/products"


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    field = error["loc"][0] if error["loc"] else "input"
    message = error["msg"].removeprefix("Value error, ")
    return f"{field}: {message}"


def _render_form(
    request: Request,
    admin: User,
    *,
    action: str,
    values: dict[str, Any],
    product_id: int | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> Response:
    """Render the shared create/edit form, preserving what was submitted."""
    return render(
        request,
        "admin/product_form.html",
        user=admin,
        action=action,
        values=values,
        product_id=product_id,
        levels=LEVELS,
        error=error,
        status_code=status_code,
    )


def _submitted(
    title: str, description: str, category: str, level: str, price: str
) -> dict[str, Any]:
    return {
        "title": title,
        "description": description,
        "category": category,
        "level": level,
        "price": price,
    }


@router.get("/products")
def list_products(request: Request, session: SessionDep, admin: AdminUser) -> Response:
    return render(
        request,
        "admin/products.html",
        user=admin,
        products=product_service.list_products(session),
    )


@router.get("/products/new")
def new_product_form(request: Request, admin: AdminUser) -> Response:
    return _render_form(
        request,
        admin,
        action="/admin/products/new",
        values={
            "title": "",
            "description": "",
            "category": "",
            "level": "beginner",
            "price": "0.00",
        },
    )


@router.post("/products/new")
def create_product(
    request: Request,
    session: SessionDep,
    admin: AdminUser,
    title: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    category: Annotated[str, Form()] = "",
    level: Annotated[str, Form()] = "",
    price: Annotated[str, Form()] = "",
) -> Response:
    values = _submitted(title, description, category, level, price)
    try:
        data = ProductCreate(**values)
    except ValidationError as exc:
        return _render_form(
            request,
            admin,
            action="/admin/products/new",
            values=values,
            error=_first_error(exc),
            status_code=400,
        )

    product_service.create_product(session, data)
    return RedirectResponse(PRODUCTS_URL, status_code=303)


@router.get("/products/{product_id}/edit")
def edit_product_form(
    request: Request, session: SessionDep, admin: AdminUser, product_id: int
) -> Response:
    product = product_service.get_product(session, product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found."
        )

    return _render_form(
        request,
        admin,
        action=f"/admin/products/{product_id}/edit",
        product_id=product_id,
        values={
            "title": product.title,
            "description": product.description,
            "category": product.category,
            "level": product.level,
            "price": f"{product.price:.2f}",
        },
    )


@router.post("/products/{product_id}/edit")
def edit_product(
    request: Request,
    session: SessionDep,
    admin: AdminUser,
    product_id: int,
    title: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    category: Annotated[str, Form()] = "",
    level: Annotated[str, Form()] = "",
    price: Annotated[str, Form()] = "",
) -> Response:
    values = _submitted(title, description, category, level, price)
    action = f"/admin/products/{product_id}/edit"
    try:
        data = ProductUpdate(**values)
    except ValidationError as exc:
        return _render_form(
            request,
            admin,
            action=action,
            product_id=product_id,
            values=values,
            error=_first_error(exc),
            status_code=400,
        )

    if product_service.update_product(session, product_id, data) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found."
        )
    return RedirectResponse(PRODUCTS_URL, status_code=303)


@router.post("/products/{product_id}/delete")
def delete_product(session: SessionDep, admin: AdminUser, product_id: int) -> Response:
    if not product_service.delete_product(session, product_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found."
        )
    return RedirectResponse(PRODUCTS_URL, status_code=303)
