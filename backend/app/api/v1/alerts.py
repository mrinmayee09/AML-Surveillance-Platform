"""Alert management and the reactive AML monitoring view."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import get_actor, get_current_user, require_alerts_update
from app.db.base import get_db
from app.models import Alert, Customer, Investigation, User
from app.schemas.alert import (
    AlertAssignRequest,
    AlertDetail,
    AlertListItem,
    AlertStatusUpdate,
    ReactiveOverview,
)
from app.schemas.common import Page
from app.services import alert_service, reactive_service
from app.services.audit_service import Actor

router = APIRouter(tags=["alerts"])

SORTABLE = {
    "raised_at": Alert.raised_at,
    "risk_score": Alert.risk_score,
    "alert_ref": Alert.alert_ref,
    "status": Alert.status,
}


def _load(db: Session, alert_ref: str) -> Alert:
    alert = db.scalar(select(Alert).where(Alert.alert_ref == alert_ref))
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"No alert {alert_ref}."},
        )
    return alert


@router.get("/alerts", response_model=Page[AlertListItem])
def list_alerts(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    search: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    source: Optional[str] = Query(None, pattern="^(PROACTIVE|REACTIVE|NETWORK|INTEGRITY)$"),
    risk_level: Optional[str] = Query(None, pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$"),
    alert_type: Optional[str] = None,
    customer_ref: Optional[str] = None,
    assignee: Optional[str] = None,
    open_only: bool = False,
    sort_by: str = Query("raised_at"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    stmt = select(Alert)
    count_stmt = select(func.count(Alert.id))
    conditions = []

    if search:
        needle = f"%{search.strip()}%"
        conditions.append(
            or_(
                Alert.alert_ref.ilike(needle),
                Alert.title.ilike(needle),
                Alert.alert_type.ilike(needle),
            )
        )
    if status_filter:
        conditions.append(Alert.status == status_filter.upper())
    if source:
        conditions.append(Alert.source == source)
    if risk_level:
        conditions.append(Alert.risk_level == risk_level)
    if alert_type:
        conditions.append(Alert.alert_type == alert_type.upper())
    if open_only:
        conditions.append(Alert.status.in_(["NEW", "UNDER_REVIEW", "ESCALATED"]))
    if customer_ref:
        customer = db.scalar(select(Customer).where(Customer.customer_ref == customer_ref))
        conditions.append(Alert.customer_id == (customer.id if customer else -1))
    if assignee:
        user = db.scalar(select(User).where(User.username == assignee))
        conditions.append(Alert.assignee_id == (user.id if user else -1))

    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = int(db.scalar(count_stmt) or 0)
    column = SORTABLE.get(sort_by, Alert.raised_at)
    stmt = stmt.order_by(column.desc() if sort_dir == "desc" else column.asc())
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()

    return Page[AlertListItem](
        items=[AlertListItem(**alert_service.to_list_item(a)) for a in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=max((total + page_size - 1) // page_size, 1),
    )


@router.get("/alerts/stats")
def alert_stats(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Counts by status, source and type for the alert page header."""
    by_source = {
        source: int(count)
        for source, count in db.execute(
            select(Alert.source, func.count(Alert.id)).group_by(Alert.source)
        ).all()
    }
    by_type = {
        alert_type: int(count)
        for alert_type, count in db.execute(
            select(Alert.alert_type, func.count(Alert.id))
            .group_by(Alert.alert_type)
            .order_by(func.count(Alert.id).desc())
        ).all()
    }
    return {
        "by_status": alert_service.status_counts(db),
        "by_source": by_source,
        "by_type": by_type,
        "open_total": alert_service.open_alert_count(db),
        "total": int(db.scalar(select(func.count(Alert.id))) or 0),
    }


@router.get("/reactive/overview", response_model=ReactiveOverview)
def reactive_overview(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    limit: int = Query(40, ge=1, le=100),
):
    """Reactive AML monitoring page: narrative pattern cards."""
    cards = reactive_service.build_pattern_cards(db, limit=limit)
    pattern_counts: dict[str, int] = {}
    for card in cards:
        key = card["pattern_code"]
        pattern_counts[key] = pattern_counts.get(key, 0) + 1

    total = int(
        db.scalar(select(func.count(Alert.id)).where(Alert.source == "REACTIVE")) or 0
    )
    open_count = int(
        db.scalar(
            select(func.count(Alert.id)).where(
                Alert.source == "REACTIVE",
                Alert.status.in_(["NEW", "UNDER_REVIEW", "ESCALATED"]),
            )
        )
        or 0
    )

    return ReactiveOverview(
        window_label="Last 30 days of settled activity",
        total_alerts=total,
        open_alerts=open_count,
        pattern_counts=pattern_counts,
        cards=cards,  # type: ignore[arg-type]
        advisory=reactive_service.REACTIVE_ADVISORY,
    )


@router.post("/reactive/run")
def run_reactive_sweep(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _: User = Depends(require_alerts_update),
    customer_ref: Optional[str] = None,
):
    """Trigger a reactive monitoring sweep (all customers, or one)."""
    from app.services import audit_service

    customers = None
    if customer_ref:
        customer = db.scalar(select(Customer).where(Customer.customer_ref == customer_ref))
        if customer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": f"No customer {customer_ref}."},
            )
        customers = [customer]

    created = reactive_service.run_monitoring_sweep(db, customers=customers)
    audit_service.record(
        db,
        actor,
        action="REACTIVE_SWEEP_RUN",
        resource_type="SYSTEM",
        resource_ref=customer_ref or "ALL_CUSTOMERS",
        new_state=f"{len(created)} alerts",
        detail=f"Reactive monitoring sweep raised {len(created)} alert(s).",
    )
    db.commit()
    return {
        "alerts_created": len(created),
        "alert_refs": [a.alert_ref for a in created],
        "scope": customer_ref or "all customers",
    }


@router.get("/alerts/{alert_ref}", response_model=AlertDetail)
def get_alert(
    alert_ref: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    alert = _load(db, alert_ref)
    investigation = db.scalar(
        select(Investigation).where(Investigation.alert_id == alert.id).limit(1)
    )
    return AlertDetail(
        **alert_service.to_list_item(alert),
        explanation=alert.explanation,
        evidence=alert.evidence or {},
        disposition_note=alert.disposition_note,
        closed_at=alert.closed_at,
        investigation_ref=investigation.case_ref if investigation else None,
        advisory=alert_service.ALERT_ADVISORY,
    )


@router.patch("/alerts/{alert_ref}/status", response_model=AlertDetail)
def update_alert_status(
    alert_ref: str,
    payload: AlertStatusUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _: User = Depends(require_alerts_update),
):
    alert = _load(db, alert_ref)
    try:
        alert_service.transition(db, alert, payload.status, actor, note=payload.note)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_transition", "message": str(exc)},
        ) from exc
    db.commit()
    return get_alert(alert_ref, db, _)


@router.post("/alerts/{alert_ref}/assign", response_model=AlertDetail)
def assign_alert(
    alert_ref: str,
    payload: AlertAssignRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _: User = Depends(require_alerts_update),
):
    alert = _load(db, alert_ref)
    assignee = db.scalar(select(User).where(User.username == payload.assignee_username))
    if assignee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "not_found",
                "message": f"No user named {payload.assignee_username}.",
            },
        )
    alert_service.assign(db, alert, assignee, actor)
    db.commit()
    return get_alert(alert_ref, db, _)
