"""Public catalog browsing: listing, search, filter, and product detail."""

from fastapi import APIRouter, HTTPException, Query, Request, status
from starlette.responses import RedirectResponse, Response

from app.core.dependencies import CurrentUser, SessionDep
from app.core.templates import render
from app.services import product_service

router = APIRouter(tags=["catalog"])


@router.get("/")
def index() -> Response:
    """The catalog is the front door."""
    return RedirectResponse("/catalog", status_code=307)


@router.get("/catalog")
def catalog(
    request: Request,
    session: SessionDep,
    user: CurrentUser,
    q: str | None = Query(default=None, max_length=255),
    category: str | None = Query(default=None, max_length=100),
) -> Response:
    products = product_service.list_products(session, q=q, category=category)
    return render(
        request,
        "pages/catalog.html",
        user=user,
        products=products,
        categories=product_service.list_categories(session),
        q=q or "",
        selected_category=category or "",
    )


@router.get("/product/{product_id}")
def product_detail(
    request: Request,
    session: SessionDep,
    user: CurrentUser,
    product_id: int,
) -> Response:
    product = product_service.get_product(session, product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found.",
        )
    return render(request, "pages/product_detail.html", user=user, product=product)
