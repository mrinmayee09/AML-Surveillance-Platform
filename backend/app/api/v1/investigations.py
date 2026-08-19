"""Investigation workspace endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import get_actor, get_current_user, require_investigations_write
from app.db.base import get_db
from app.models import Alert, Customer, Investigation, Network, User
from app.schemas.alert import (
    InvestigationAssignRequest,
    InvestigationCreate,
    InvestigationDetail,
    InvestigationListItem,
    InvestigationNoteCreate,
    InvestigationStatusUpdate,
    NoteOut,
)
from app.schemas.common import Page
from app.services import investigation_service
from app.services.audit_service import Actor

router = APIRouter(prefix="/investigations", tags=["investigations"])

SORTABLE = {
    "opened_at": Investigation.opened_at,
    "risk_score": Investigation.risk_score,
    "case_ref": Investigation.case_ref,
    "priority": Investigation.priority,
}


def _load(db: Session, case_ref: str) -> Investigation:
    investigation = db.scalar(
        select(Investigation).where(Investigation.case_ref == case_ref)
    )
    if investigation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"No investigation {case_ref}."},
        )
    return investigation


def _detail(db: Session, investigation: Investigation) -> InvestigationDetail:
    extras = investigation_service.build_detail(db, investigation)
    return InvestigationDetail(
        **investigation_service.to_list_item(db, investigation),
        summary=investigation.summary or "",
        notes=[NoteOut.model_validate(n) for n in investigation.notes],
        timeline=extras["timeline"],
        alerts=extras["alerts"],
        risk_factors=extras["risk_factors"],
        linked_transactions=extras["linked_transactions"],
        network_snapshot=extras["network_snapshot"],
        advisory=extras["advisory"],
    )


@router.get("", response_model=Page[InvestigationListItem])
def list_investigations(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    search: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    priority: Optional[str] = Query(None, pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$"),
    assignee: Optional[str] = None,
    open_only: bool = False,
    sort_by: str = Query("opened_at"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    stmt = select(Investigation)
    count_stmt = select(func.count(Investigation.id))
    conditions = []

    if search:
        needle = f"%{search.strip()}%"
        conditions.append(
            or_(Investigation.case_ref.ilike(needle), Investigation.title.ilike(needle))
        )
    if status_filter:
        conditions.append(Investigation.status == status_filter.upper())
    if priority:
        conditions.append(Investigation.priority == priority)
    if open_only:
        conditions.append(
            Investigation.status.notin_(["CLOSED_CLEARED", "CLOSED_REPORTED"])
        )
    if assignee:
        user = db.scalar(select(User).where(User.username == assignee))
        conditions.append(Investigation.assignee_id == (user.id if user else -1))

    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = int(db.scalar(count_stmt) or 0)
    column = SORTABLE.get(sort_by, Investigation.opened_at)
    stmt = stmt.order_by(column.desc() if sort_dir == "desc" else column.asc())
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()

    return Page[InvestigationListItem](
        items=[
            InvestigationListItem(**investigation_service.to_list_item(db, i)) for i in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
        pages=max((total + page_size - 1) // page_size, 1),
    )


@router.post("", response_model=InvestigationDetail, status_code=status.HTTP_201_CREATED)
def create_investigation(
    payload: InvestigationCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    user: User = Depends(require_investigations_write),
):
    alert = None
    customer = None
    network = None

    if payload.alert_ref:
        alert = db.scalar(select(Alert).where(Alert.alert_ref == payload.alert_ref))
        if alert is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": f"No alert {payload.alert_ref}."},
            )
    if payload.customer_ref:
        customer = db.scalar(
            select(Customer).where(Customer.customer_ref == payload.customer_ref)
        )
        if customer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "not_found",
                    "message": f"No customer {payload.customer_ref}.",
                },
            )
    if payload.network_ref:
        network = db.scalar(
            select(Network).where(Network.network_ref == payload.network_ref)
        )
        if network is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "not_found",
                    "message": f"No network {payload.network_ref}.",
                },
            )

    if alert is None and customer is None and network is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "no_subject",
                "message": (
                    "An investigation must reference at least one of alert_ref, "
                    "customer_ref or network_ref."
                ),
            },
        )

    investigation = investigation_service.create_investigation(
        db=db,
        title=payload.title,
        actor=actor,
        author=user,
        alert=alert,
        customer=customer,
        network=network,
        priority=payload.priority,
        summary=payload.summary or "",
        assignee=user,
    )
    db.commit()
    return _detail(db, investigation)


@router.get("/{case_ref}", response_model=InvestigationDetail)
def get_investigation(
    case_ref: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return _detail(db, _load(db, case_ref))


@router.post("/{case_ref}/notes", response_model=InvestigationDetail)
def add_note(
    case_ref: str,
    payload: InvestigationNoteCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    user: User = Depends(require_investigations_write),
):
    investigation = _load(db, case_ref)
    investigation_service.record_note(
        db=db,
        investigation=investigation,
        body=payload.body,
        author=user,
        actor=actor,
        note_type=payload.note_type,
    )
    db.commit()
    db.refresh(investigation)
    return _detail(db, investigation)


@router.patch("/{case_ref}/status", response_model=InvestigationDetail)
def update_status(
    case_ref: str,
    payload: InvestigationStatusUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    user: User = Depends(require_investigations_write),
):
    investigation = _load(db, case_ref)
    try:
        investigation_service.transition(
            db=db,
            investigation=investigation,
            new_status=payload.status,
            actor=actor,
            author=user,
            outcome=payload.outcome,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_transition", "message": str(exc)},
        ) from exc
    db.commit()
    db.refresh(investigation)
    return _detail(db, investigation)


@router.post("/{case_ref}/assign", response_model=InvestigationDetail)
def assign_investigation(
    case_ref: str,
    payload: InvestigationAssignRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _: User = Depends(require_investigations_write),
):
    investigation = _load(db, case_ref)
    assignee = db.scalar(select(User).where(User.username == payload.assignee_username))
    if assignee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "not_found",
                "message": f"No user named {payload.assignee_username}.",
            },
        )
    investigation_service.assign(db, investigation, assignee, actor)
    db.commit()
    db.refresh(investigation)
    return _detail(db, investigation)
