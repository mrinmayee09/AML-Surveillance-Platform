"""Alert creation and lifecycle management.

Alert titles and explanations use the platform's mandated language: activity is
described as "potentially suspicious", "requiring investigation" or a "potential
laundering pattern". No alert asserts that a customer is a money launderer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Alert, Customer, Network, Transaction, User
from app.models.enums import AlertSource, AlertStatus, Severity
from app.services import audit_service
from app.services.audit_service import Actor
from app.services.risk_service import RiskResult

ALERT_ADVISORY = (
    "This alert reflects model- and rule-generated risk indicators. It means the "
    "activity requires investigation under the institution's AML procedures. It is "
    "not a determination that an offence occurred, and it is not evidence."
)

# Status transitions an analyst is permitted to make
ALLOWED_TRANSITIONS: Dict[str, set[str]] = {
    AlertStatus.NEW.value: {
        AlertStatus.UNDER_REVIEW.value,
        AlertStatus.ESCALATED.value,
        AlertStatus.CLEARED.value,
    },
    AlertStatus.UNDER_REVIEW.value: {
        AlertStatus.ESCALATED.value,
        AlertStatus.CLEARED.value,
        AlertStatus.CONFIRMED_SUSPICIOUS.value,
    },
    AlertStatus.ESCALATED.value: {
        AlertStatus.CONFIRMED_SUSPICIOUS.value,
        AlertStatus.CLEARED.value,
        AlertStatus.UNDER_REVIEW.value,
    },
    AlertStatus.CLEARED.value: {AlertStatus.UNDER_REVIEW.value},
    AlertStatus.CONFIRMED_SUSPICIOUS.value: {AlertStatus.UNDER_REVIEW.value},
}

_TERMINAL = {AlertStatus.CLEARED.value, AlertStatus.CONFIRMED_SUSPICIOUS.value}


def _new_ref() -> str:
    return f"ALERT-{uuid.uuid4().hex[:8].upper()}"


def severity_for(risk_level: str) -> str:
    return {
        "LOW": Severity.LOW.value,
        "MEDIUM": Severity.MEDIUM.value,
        "HIGH": Severity.HIGH.value,
        "CRITICAL": Severity.CRITICAL.value,
    }.get(risk_level, Severity.MEDIUM.value)


def create_alert(
    db: Session,
    source: str,
    alert_type: str,
    title: str,
    explanation: str,
    risk_score: float,
    risk_level: str,
    customer_id: Optional[int] = None,
    transaction_id: Optional[int] = None,
    account_id: Optional[int] = None,
    network_id: Optional[int] = None,
    rule_code: Optional[str] = None,
    evidence: Optional[Dict[str, Any]] = None,
    raised_at: Optional[datetime] = None,
    status: str = AlertStatus.NEW.value,
    assignee_id: Optional[int] = None,
) -> Alert:
    alert = Alert(
        alert_ref=_new_ref(),
        source=source,
        alert_type=alert_type,
        title=title,
        explanation=explanation,
        evidence=evidence or {},
        rule_code=rule_code,
        customer_id=customer_id,
        transaction_id=transaction_id,
        account_id=account_id,
        network_id=network_id,
        risk_score=round(risk_score, 1),
        risk_level=risk_level,
        severity=severity_for(risk_level),
        status=status,
        assignee_id=assignee_id,
        raised_at=raised_at or datetime.utcnow(),
    )
    db.add(alert)

    if customer_id:
        customer = db.get(Customer, customer_id)
        if customer:
            customer.previous_alert_count = (customer.previous_alert_count or 0) + 1
            customer.under_monitoring = True
    return alert


def raise_proactive_alert(
    db: Session,
    customer: Customer,
    result: RiskResult,
    transaction_id: Optional[int] = None,
    order_ref: Optional[str] = None,
) -> Alert:
    """Alert produced by the pre-transaction proactive layer."""
    top = result.factors[0].label if result.factors else "behavioural risk indicators"
    verdict = (
        "blocked pending escalation"
        if result.decision == "BLOCK"
        else "held for analyst review"
    )
    explanation = (
        f"Pre-transaction assessment scored {result.score}/100 ({result.level}) for "
        f"customer {customer.customer_ref}. The payment was {verdict}. "
        f"The strongest contributing signal was: {top}. "
        + " ".join(f"[{f.label}: +{f.contribution}] {f.detail}" for f in result.factors[:4])
    )
    return create_alert(
        db=db,
        source=AlertSource.PROACTIVE.value,
        alert_type="PROACTIVE_RISK_ELEVATED",
        title=(
            f"Potentially suspicious payment attempt requires investigation - "
            f"{customer.name}"
        ),
        explanation=explanation,
        risk_score=result.score,
        risk_level=result.level,
        customer_id=customer.id,
        transaction_id=transaction_id,
        rule_code=result.triggered_rule_codes[0] if result.triggered_rule_codes else None,
        evidence={
            "order_ref": order_ref,
            "decision": result.decision,
            "model_probability": result.model_probability,
            "triggered_rules": result.triggered_rule_codes,
            "factors": result.factor_dicts(),
            "layer": "PROACTIVE (pre-transaction)",
        },
    )


def transition(
    db: Session,
    alert: Alert,
    new_status: str,
    actor: Actor,
    note: Optional[str] = None,
) -> Alert:
    """Move an alert to a new status, writing an audit entry.

    Raises ValueError on an illegal transition so the API can return 400.
    """
    previous = alert.status
    if new_status == previous:
        raise ValueError(f"Alert is already in status {previous}")
    allowed = ALLOWED_TRANSITIONS.get(previous, set())
    if new_status not in allowed:
        raise ValueError(
            f"Cannot move an alert from {previous} to {new_status}. "
            f"Permitted transitions: {', '.join(sorted(allowed)) or 'none'}"
        )

    alert.status = new_status
    if new_status in _TERMINAL:
        alert.closed_at = datetime.utcnow()
        if note:
            alert.disposition_note = note
    else:
        alert.closed_at = None

    audit_service.record(
        db,
        actor,
        action="ALERT_STATUS_CHANGED",
        resource_type="ALERT",
        resource_ref=alert.alert_ref,
        previous_state=previous,
        new_state=new_status,
        detail=note or f"Status changed from {previous} to {new_status}.",
        context={"alert_type": alert.alert_type, "risk_score": alert.risk_score},
    )
    return alert


def assign(db: Session, alert: Alert, assignee: User, actor: Actor) -> Alert:
    previous = alert.assignee.username if alert.assignee else None
    alert.assignee_id = assignee.id
    if alert.status == AlertStatus.NEW.value:
        alert.status = AlertStatus.UNDER_REVIEW.value

    audit_service.record(
        db,
        actor,
        action="ALERT_ASSIGNED",
        resource_type="ALERT",
        resource_ref=alert.alert_ref,
        previous_state=previous,
        new_state=assignee.username,
        detail=f"Alert assigned to {assignee.full_name} ({assignee.username}).",
    )
    return alert


def status_counts(db: Session) -> Dict[str, int]:
    rows = db.execute(
        select(Alert.status, func.count(Alert.id)).group_by(Alert.status)
    ).all()
    counts = {status.value: 0 for status in AlertStatus}
    for status, count in rows:
        counts[status] = int(count)
    return counts


def open_alert_count(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count(Alert.id)).where(
                Alert.status.in_(
                    [
                        AlertStatus.NEW.value,
                        AlertStatus.UNDER_REVIEW.value,
                        AlertStatus.ESCALATED.value,
                    ]
                )
            )
        )
        or 0
    )


def to_list_item(alert: Alert) -> Dict[str, Any]:
    """Flatten an alert row for the API list schema."""
    return {
        "id": alert.id,
        "alert_ref": alert.alert_ref,
        "source": alert.source,
        "alert_type": alert.alert_type,
        "title": alert.title,
        "rule_code": alert.rule_code,
        "risk_score": alert.risk_score,
        "risk_level": alert.risk_level,
        "severity": alert.severity,
        "status": alert.status,
        "raised_at": alert.raised_at,
        "customer_ref": alert.customer.customer_ref if alert.customer else None,
        "customer_name": alert.customer.name if alert.customer else None,
        "transaction_ref": alert.transaction.txn_ref if alert.transaction else None,
        "network_ref": alert.network.network_ref if alert.network else None,
        "assignee_name": alert.assignee.full_name if alert.assignee else None,
    }
