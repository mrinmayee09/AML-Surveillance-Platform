"""Rules engine administration."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_actor, get_current_user, require_rules_write
from app.db.base import get_db
from app.models import Rule, User
from app.schemas.dashboard import RuleCreate, RuleOut, RuleUpdate
from app.services import audit_service
from app.services.audit_service import Actor

router = APIRouter(prefix="/rules", tags=["rules"])


def _load(db: Session, code: str) -> Rule:
    rule = db.scalar(select(Rule).where(Rule.code == code.upper()))
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"No rule {code}."},
        )
    return rule


@router.get("", response_model=List[RuleOut])
def list_rules(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    layer: Optional[str] = Query(None, pattern="^(PROACTIVE|REACTIVE|NETWORK|INTEGRITY)$"),
    category: Optional[str] = None,
    enabled_only: bool = False,
):
    stmt = select(Rule)
    if layer:
        stmt = stmt.where(Rule.layer == layer)
    if category:
        stmt = stmt.where(Rule.category == category.upper())
    if enabled_only:
        stmt = stmt.where(Rule.enabled.is_(True))
    rows = db.scalars(stmt.order_by(Rule.layer, Rule.score_weight.desc())).all()
    return [RuleOut.model_validate(r) for r in rows]


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(
    payload: RuleCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _: User = Depends(require_rules_write),
):
    existing = db.scalar(select(Rule).where(Rule.code == payload.code))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "rule_exists",
                "message": f"A rule with code {payload.code} already exists.",
            },
        )

    rule = Rule(**payload.model_dump(), triggered_count=0, enabled=True)
    db.add(rule)
    db.flush()

    audit_service.record(
        db,
        actor,
        action="RULE_CREATED",
        resource_type="RULE",
        resource_ref=rule.code,
        new_state="ENABLED",
        detail=(
            f"Created {rule.layer} rule {rule.code} at threshold {rule.threshold} "
            f"{rule.threshold_unit}, weight {rule.score_weight}."
        ),
    )
    db.commit()
    return RuleOut.model_validate(rule)


@router.patch("/{code}", response_model=RuleOut)
def update_rule(
    code: str,
    payload: RuleUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _: User = Depends(require_rules_write),
):
    """Retune or toggle a rule.

    Because the engine reads thresholds from this table at evaluation time, a
    change here immediately alters what the detection layers flag - which is why
    every change is audited with its before and after values.
    """
    rule = _load(db, code)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "no_changes", "message": "No fields supplied to update."},
        )

    before = {field: getattr(rule, field) for field in changes}
    for field, value in changes.items():
        setattr(rule, field, value)

    if "enabled" in changes:
        previous_state = "ENABLED" if before["enabled"] else "DISABLED"
        new_state = "ENABLED" if rule.enabled else "DISABLED"
    else:
        previous_state = str(before)
        new_state = str(changes)

    audit_service.record(
        db,
        actor,
        action="RULE_UPDATED",
        resource_type="RULE",
        resource_ref=rule.code,
        previous_state=previous_state[:64],
        new_state=new_state[:64],
        detail=(
            f"Rule {rule.code} updated. Before: {before}. After: {changes}. "
            "Detection behaviour changes immediately."
        ),
        context={"before": before, "after": changes},
    )
    db.commit()
    return RuleOut.model_validate(rule)


@router.get("/{code}", response_model=RuleOut)
def get_rule(
    code: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return RuleOut.model_validate(_load(db, code))
