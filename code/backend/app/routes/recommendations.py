"""User recommendations dashboard route — reads stored data only, 0 LLM calls."""

from fastapi import APIRouter, Request
from sqlmodel import col, select
from starlette.responses import RedirectResponse, Response

from app.core.dependencies import CurrentUser, SessionDep
from app.core.templates import render
from app.models import Product
from app.services.recommendation_service import latest_recommendation

router = APIRouter(tags=["recommendations"])

COLD_START_MESSAGE = (
    "SmartReco doesn't know you yet — pick a direction. "
    "Here's a spread across the catalog: open anything that looks interesting, "
    "and recommendations will shape themselves around what you actually do."
)


@router.get("/dashboard")
def dashboard(
    request: Request,
    session: SessionDep,
    user: CurrentUser,
) -> Response:
    """Render the user's recommendation dashboard.

    Strict Invariant: Reads stored DB data ONLY. Zero LLM calls on GET requests.
    """
    if user is None:
        return RedirectResponse("/login", status_code=303)

    rec = latest_recommendation(session, user.id)

    if rec is not None and rec.product_ids:
        # Hydrate recommended products in stored order
        statement = select(Product).where(col(Product.id).in_(rec.product_ids))
        products_by_id = {p.id: p for p in session.exec(statement).all()}
        products = [
            products_by_id[pid] for pid in rec.product_ids if pid in products_by_id
        ]
        return render(
            request,
            "pages/dashboard.html",
            user=user,
            recommendation=rec,
            products=products,
            is_cold_start=False,
        )

    # Cold start: select 1 course per distinct category from SQL database
    all_products = session.exec(
        select(Product).order_by(
            col(Product.category),
            col(Product.level),
            col(Product.price),
        )
    ).all()

    cold_products: list[Product] = []
    seen_categories: set[str] = set()
    for product in all_products:
        if product.category not in seen_categories:
            seen_categories.add(product.category)
            cold_products.append(product)
            if len(cold_products) >= 6:
                break

    return render(
        request,
        "pages/dashboard.html",
        user=user,
        recommendation=None,
        cold_message=COLD_START_MESSAGE,
        products=cold_products,
        is_cold_start=True,
    )
