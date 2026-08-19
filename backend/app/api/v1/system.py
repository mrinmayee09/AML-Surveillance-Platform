"""Dashboard, audit log, model insights, settings and the demo runner."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import (
    get_actor,
    get_current_user,
    require_audit_read,
    require_gateway,
)
from app.core.security import ROLE_PERMISSIONS
from app.db.base import engine, get_db
from app.models import AuditLog, User
from app.schemas.alert import AuditLogItem
from app.schemas.common import Page
from app.schemas.dashboard import (
    DashboardOverview,
    DemoRunRequest,
    DemoRunResponse,
    ModelInsightsResponse,
    SystemSettings,
    ThresholdSettings,
)
from app.services import dashboard_service, demo_service, model_service
from app.services.audit_service import Actor

router = APIRouter(tags=["system"])


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get("/dashboard/overview", response_model=DashboardOverview)
def dashboard_overview(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    window: str = Query("7D", pattern="^(24H|7D|30D|90D|24h|7d|30d|90d)$"),
):
    """Every figure here is a live SQL aggregate over the monitored data."""
    return DashboardOverview(**dashboard_service.build_overview(db, window))


# ---------------------------------------------------------------------------
# Audit logs (ADMIN only)
# ---------------------------------------------------------------------------


@router.get("/audit-logs", response_model=Page[AuditLogItem])
def list_audit_logs(
    db: Session = Depends(get_db),
    _: User = Depends(require_audit_read),
    search: Optional[str] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    actor_name: Optional[str] = Query(None, alias="actor"),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """Append-only audit trail. Rows are never modified or deleted."""
    stmt = select(AuditLog)
    count_stmt = select(func.count(AuditLog.id))
    conditions = []

    if search:
        needle = f"%{search.strip()}%"
        conditions.append(
            or_(
                AuditLog.resource_ref.ilike(needle),
                AuditLog.action.ilike(needle),
                AuditLog.detail.ilike(needle),
                AuditLog.actor.ilike(needle),
            )
        )
    if action:
        conditions.append(AuditLog.action == action.upper())
    if resource_type:
        conditions.append(AuditLog.resource_type == resource_type.upper())
    if actor_name:
        conditions.append(AuditLog.actor == actor_name)
    if date_from:
        conditions.append(AuditLog.occurred_at >= date_from)
    if date_to:
        conditions.append(AuditLog.occurred_at <= date_to)

    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = int(db.scalar(count_stmt) or 0)
    rows = db.scalars(
        stmt.order_by(AuditLog.occurred_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return Page[AuditLogItem](
        items=[AuditLogItem.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=max((total + page_size - 1) // page_size, 1),
    )


@router.get("/audit-logs/actions")
def audit_action_facets(
    db: Session = Depends(get_db),
    _: User = Depends(require_audit_read),
):
    """Distinct actions / resource types / actors, for the filter dropdowns."""
    actions = [
        row[0]
        for row in db.execute(
            select(AuditLog.action).group_by(AuditLog.action).order_by(AuditLog.action)
        ).all()
    ]
    resources = [
        row[0]
        for row in db.execute(
            select(AuditLog.resource_type)
            .group_by(AuditLog.resource_type)
            .order_by(AuditLog.resource_type)
        ).all()
    ]
    actors = [
        row[0]
        for row in db.execute(
            select(AuditLog.actor).group_by(AuditLog.actor).order_by(AuditLog.actor)
        ).all()
    ]
    return {"actions": actions, "resource_types": resources, "actors": actors}


# ---------------------------------------------------------------------------
# Model insights
# ---------------------------------------------------------------------------


@router.get("/models/insights", response_model=ModelInsightsResponse)
def model_insights(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """What each model actually is, read from the trained artifacts."""
    return ModelInsightsResponse(**model_service.build_insights(db))


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


@router.get("/demo/scenarios")
def demo_scenarios(_: User = Depends(get_current_user)):
    return {
        "scenarios": [
            {"key": key, **value} for key, value in demo_service.SCENARIOS.items()
        ]
    }


@router.post("/demo/run", response_model=DemoRunResponse)
def run_demo(
    payload: DemoRunRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _: User = Depends(require_gateway),
):
    """Execute the full AML narrative end-to-end against the live database."""
    try:
        result = demo_service.run_demo(
            db=db,
            actor=actor,
            scenario=payload.scenario,
            claimed_amount=payload.claimed_amount,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "demo_failed", "message": str(exc)},
        ) from exc
    return DemoRunResponse(**result)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@router.get("/settings", response_model=SystemSettings)
def get_settings(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Effective configuration.

    Note what is NOT here: no secret, key or credential is ever returned to the
    client. Only thresholds, engine identities and role capabilities.
    """
    from app import __version__
    from app.gnn.registry import get_gnn_engine
    from app.ml.registry import get_proactive_model

    model = get_proactive_model()
    gnn = get_gnn_engine()

    return SystemSettings(
        app_name=settings.app_name,
        environment=settings.environment,
        thresholds=ThresholdSettings(
            medium=settings.risk_threshold_medium,
            high=settings.risk_threshold_high,
            critical=settings.risk_threshold_critical,
        ),
        database_engine=engine.dialect.name,
        ml_engine={
            "name": model.name,
            "version": model.version,
            "type": model.model_type,
            "trained": model.trained,
            "training_data": model.training_data,
        },
        gnn_engine={
            "name": gnn.name,
            "version": gnn.version,
            "architecture": gnn.architecture,
            "trained": gnn.trained,
            "training_data": gnn.training_data,
        },
        roles={role: perms for role, perms in ROLE_PERMISSIONS.items()},
        version=__version__,
    )
