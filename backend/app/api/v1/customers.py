"""Customer endpoints: list, detail, risk profile, proactive overview."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.base import get_db
from app.models import Customer, User
from app.schemas.common import Page
from app.schemas.customer import (
    AccountSummary,
    CustomerDetail,
    CustomerListItem,
    CustomerRiskProfile,
    ProactiveOverview,
)
from app.services import customer_service

router = APIRouter(tags=["customers"])


def _load(db: Session, customer_ref: str) -> Customer:
    customer = db.scalar(select(Customer).where(Customer.customer_ref == customer_ref))
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"No customer {customer_ref}."},
        )
    return customer


@router.get("/customers", response_model=Page[CustomerListItem])
def list_customers(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    search: Optional[str] = Query(None, max_length=64),
    risk_level: Optional[str] = Query(None, pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$"),
    trend: Optional[str] = Query(None, pattern="^(INCREASING|STABLE|DECREASING)$"),
    monitored: Optional[bool] = None,
    pep_only: Optional[bool] = None,
    sort_by: str = Query(
        "current_risk_score", pattern="^(current_risk_score|name|account_age_years)$"
    ),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    stmt = select(Customer)
    count_stmt = select(func.count(Customer.id))

    filters = []
    if search:
        like = f"%{search}%"
        filters.append(
            or_(
                Customer.customer_ref.ilike(like),
                Customer.name.ilike(like),
                Customer.city.ilike(like),
            )
        )
    if risk_level:
        filters.append(Customer.current_risk_level == risk_level)
    if trend:
        filters.append(Customer.risk_trend == trend)
    if monitored is not None:
        filters.append(Customer.under_monitoring.is_(monitored))
    if pep_only:
        filters.append(Customer.pep_flag.is_(True))

    for condition in filters:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = int(db.scalar(count_stmt) or 0)
    column = {
        "current_risk_score": Customer.current_risk_score,
        "name": Customer.name,
        "account_age_years": Customer.account_age_years,
    }[sort_by]
    stmt = stmt.order_by(column.desc() if sort_dir == "desc" else column.asc())
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()

    return Page[CustomerListItem](
        items=[CustomerListItem(**customer_service.to_list_item(c)) for c in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=max((total + page_size - 1) // page_size, 1),
    )


@router.get("/customers/proactive-overview", response_model=ProactiveOverview)
def proactive_overview(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    limit: int = Query(25, ge=1, le=100),
):
    """Portfolio view for the Proactive Risk Intelligence page."""
    return ProactiveOverview(**customer_service.proactive_overview(db, limit=limit))


@router.get("/customers/{customer_ref}", response_model=CustomerDetail)
def get_customer(
    customer_ref: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    customer = _load(db, customer_ref)
    payload = customer_service.to_list_item(customer)
    payload.update(
        {
            "email": customer.email,
            "phone": customer.phone,
            "occupation": customer.occupation,
            "onboarded_on": customer.onboarded_on,
            "entity_type": customer.entity_type,
            "risk_country_exposure": customer.risk_country_exposure,
            "baseline_avg_amount": customer.baseline_avg_amount,
            "baseline_monthly_count": customer.baseline_monthly_count,
            "baseline_counterparties": customer.baseline_counterparties,
            "accounts": [AccountSummary.model_validate(a) for a in customer.accounts],
            "behaviour": customer_service.behavioural_stats(db, customer),
        }
    )
    return CustomerDetail(**payload)


@router.get("/customers/{customer_ref}/risk", response_model=CustomerRiskProfile)
def get_customer_risk(
    customer_ref: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Recompute the customer's proactive risk with a full factor breakdown."""
    customer = _load(db, customer_ref)
    return CustomerRiskProfile(**customer_service.risk_profile(db, customer))
