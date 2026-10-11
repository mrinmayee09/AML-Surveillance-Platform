"""Investigation case management.

Every mutation (create, assign, note, status change, escalate, clear) writes both
an investigation note and an audit-log entry, so the case file and the audit
trail never disagree.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.types import utcnow
from app.models import (
    Alert,
    Customer,
    Investigation,
    InvestigationNote,
    Network,
    NetworkNode,
    RiskAssessment,
    Transaction,
    User,
)
from app.models.enums import AlertStatus, AssessmentKind, InvestigationStatus
from app.services import audit_service, network_service
from app.services.audit_service import Actor

INVESTIGATION_ADVISORY = (
    "This case file aggregates model- and rule-generated risk indicators. A risk "
    "score is not proof of criminal activity. Any conclusion must be reached by a "
    "human investigator on the evidence, and recorded as an explicit outcome."
)

ALLOWED_TRANSITIONS: Dict[str, set[str]] = {
    InvestigationStatus.OPEN.value: {
        InvestigationStatus.IN_PROGRESS.value,
        InvestigationStatus.CLOSED_CLEARED.value,
    },
    InvestigationStatus.IN_PROGRESS.value: {
        InvestigationStatus.PENDING_APPROVAL.value,
        InvestigationStatus.CLOSED_CLEARED.value,
        InvestigationStatus.CLOSED_REPORTED.value,
    },
    InvestigationStatus.PENDING_APPROVAL.value: {
        InvestigationStatus.CLOSED_REPORTED.value,
        InvestigationStatus.CLOSED_CLEARED.value,
        InvestigationStatus.IN_PROGRESS.value,
    },
    InvestigationStatus.CLOSED_CLEARED.value: {InvestigationStatus.IN_PROGRESS.value},
    InvestigationStatus.CLOSED_REPORTED.value: {InvestigationStatus.IN_PROGRESS.value},
}

_CLOSED = {
    InvestigationStatus.CLOSED_CLEARED.value,
    InvestigationStatus.CLOSED_REPORTED.value,
}


def _next_ref(db: Session) -> str:
    count = int(db.scalar(select(func.count(Investigation.id))) or 0)
    return f"CASE-{1000 + count + 1}"


def add_note(
    db: Session,
    investigation: Investigation,
    body: str,
    author: Optional[User] = None,
    note_type: str = "NOTE",
) -> InvestigationNote:
    note = InvestigationNote(
        investigation_id=investigation.id,
        author_id=author.id if author else None,
        author_name=author.full_name if author else "system",
        note_type=note_type,
        body=body,
    )
    db.add(note)
    return note


def create_investigation(
    db: Session,
    title: str,
    actor: Actor,
    author: Optional[User] = None,
    alert: Optional[Alert] = None,
    customer: Optional[Customer] = None,
    network: Optional[Network] = None,
    priority: str = "MEDIUM",
    summary: str = "",
    assignee: Optional[User] = None,
    opened_at: Optional[datetime] = None,
    status: str = InvestigationStatus.OPEN.value,
) -> Investigation:
    resolved_customer = customer or (alert.customer if alert else None)
    resolved_network = network or (alert.network if alert else None)
    risk_score = alert.risk_score if alert else (
        resolved_customer.current_risk_score if resolved_customer else 0.0
    )
    opened = opened_at or utcnow()

    investigation = Investigation(
        case_ref=_next_ref(db),
        title=title,
        summary=summary,
        alert_id=alert.id if alert else None,
        customer_id=resolved_customer.id if resolved_customer else None,
        network_id=resolved_network.id if resolved_network else None,
        status=status,
        priority=priority,
        risk_score=risk_score,
        assignee_id=assignee.id if assignee else None,
        opened_at=opened,
        due_at=opened + timedelta(days=5),
    )
    db.add(investigation)
    db.flush()

    add_note(
        db,
        investigation,
        body=(
            f"Case opened from {'alert ' + alert.alert_ref if alert else 'manual review'}."
            + (f" Linked network {resolved_network.network_ref}." if resolved_network else "")
        ),
        author=author,
        note_type="SYSTEM",
    )

    if alert and alert.status == AlertStatus.NEW.value:
        alert.status = AlertStatus.UNDER_REVIEW.value

    audit_service.record(
        db,
        actor,
        action="INVESTIGATION_CREATED",
        resource_type="INVESTIGATION",
        resource_ref=investigation.case_ref,
        new_state=investigation.status,
        detail=f"Investigation opened: {title}",
        context={
            "alert_ref": alert.alert_ref if alert else None,
            "customer_ref": resolved_customer.customer_ref if resolved_customer else None,
            "network_ref": resolved_network.network_ref if resolved_network else None,
            "priority": priority,
        },
        occurred_at=opened,
    )
    return investigation


def assign(
    db: Session, investigation: Investigation, assignee: User, actor: Actor
) -> Investigation:
    previous = investigation.assignee.username if investigation.assignee else None
    investigation.assignee_id = assignee.id
    if investigation.status == InvestigationStatus.OPEN.value:
        investigation.status = InvestigationStatus.IN_PROGRESS.value

    add_note(
        db,
        investigation,
        body=f"Case assigned to {assignee.full_name} ({assignee.username}).",
        note_type="ASSIGNMENT",
    )
    audit_service.record(
        db,
        actor,
        action="INVESTIGATION_ASSIGNED",
        resource_type="INVESTIGATION",
        resource_ref=investigation.case_ref,
        previous_state=previous,
        new_state=assignee.username,
        detail=f"Case assigned to {assignee.full_name}.",
    )
    return investigation


def record_note(
    db: Session,
    investigation: Investigation,
    body: str,
    author: User,
    actor: Actor,
    note_type: str = "NOTE",
) -> InvestigationNote:
    note = add_note(db, investigation, body=body, author=author, note_type=note_type)
    audit_service.record(
        db,
        actor,
        action="INVESTIGATION_NOTE_ADDED",
        resource_type="INVESTIGATION",
        resource_ref=investigation.case_ref,
        new_state=note_type,
        detail=body[:480],
    )
    return note


def transition(
    db: Session,
    investigation: Investigation,
    new_status: str,
    actor: Actor,
    author: Optional[User] = None,
    outcome: Optional[str] = None,
    note: Optional[str] = None,
) -> Investigation:
    previous = investigation.status
    if new_status == previous:
        raise ValueError(f"Case is already in status {previous}")
    allowed = ALLOWED_TRANSITIONS.get(previous, set())
    if new_status not in allowed:
        raise ValueError(
            f"Cannot move a case from {previous} to {new_status}. "
            f"Permitted transitions: {', '.join(sorted(allowed)) or 'none'}"
        )

    investigation.status = new_status
    if new_status in _CLOSED:
        investigation.closed_at = utcnow()
        investigation.outcome = outcome or (
            "Cleared - no further action"
            if new_status == InvestigationStatus.CLOSED_CLEARED.value
            else "Reported to compliance for regulatory filing"
        )
        # Closing a case dispositions its alert
        if investigation.alert:
            investigation.alert.status = (
                AlertStatus.CLEARED.value
                if new_status == InvestigationStatus.CLOSED_CLEARED.value
                else AlertStatus.CONFIRMED_SUSPICIOUS.value
            )
            investigation.alert.closed_at = utcnow()
            investigation.alert.disposition_note = investigation.outcome
    else:
        investigation.closed_at = None

    add_note(
        db,
        investigation,
        body=note or f"Status changed from {previous} to {new_status}.",
        author=author,
        note_type="STATUS_CHANGE",
    )
    audit_service.record(
        db,
        actor,
        action="INVESTIGATION_STATUS_CHANGED",
        resource_type="INVESTIGATION",
        resource_ref=investigation.case_ref,
        previous_state=previous,
        new_state=new_status,
        detail=note or f"Status changed from {previous} to {new_status}.",
        context={"outcome": investigation.outcome},
    )
    return investigation


def build_timeline(db: Session, investigation: Investigation) -> List[Dict[str, Any]]:
    """Merge notes, alerts and assessments into one chronological view."""
    events: List[Dict[str, Any]] = [
        {
            "at": investigation.opened_at,
            "actor": investigation.assignee.full_name if investigation.assignee else "system",
            "kind": "CASE_OPENED",
            "label": "Investigation opened",
            "detail": investigation.title,
        }
    ]

    if investigation.alert:
        events.append(
            {
                "at": investigation.alert.raised_at,
                "actor": "aml-engine",
                "kind": "ALERT_RAISED",
                "label": f"{investigation.alert.source} alert {investigation.alert.alert_ref}",
                "detail": investigation.alert.title,
            }
        )

    for note in investigation.notes:
        events.append(
            {
                "at": note.created_at,
                "actor": note.author_name,
                "kind": note.note_type,
                "label": {
                    "NOTE": "Investigator note",
                    "STATUS_CHANGE": "Status change",
                    "ASSIGNMENT": "Assignment",
                    "ESCALATION": "Escalation",
                    "SYSTEM": "System event",
                }.get(note.note_type, note.note_type.title()),
                "detail": note.body,
            }
        )

    if investigation.customer_id:
        assessments: Sequence[RiskAssessment] = db.scalars(
            select(RiskAssessment)
            .where(RiskAssessment.customer_id == investigation.customer_id)
            .order_by(RiskAssessment.assessed_at.desc())
            .limit(5)
        ).all()
        for assessment in assessments:
            events.append(
                {
                    "at": assessment.assessed_at,
                    "actor": assessment.model_name,
                    "kind": "RISK_ASSESSMENT",
                    "label": f"{assessment.kind} assessment {assessment.risk_score:.0f}/100",
                    "detail": (
                        f"{assessment.risk_level} ({assessment.trend}), decision "
                        f"{assessment.decision}."
                    ),
                }
            )

    if investigation.closed_at:
        events.append(
            {
                "at": investigation.closed_at,
                "actor": investigation.assignee.full_name if investigation.assignee else "system",
                "kind": "CASE_CLOSED",
                "label": "Investigation closed",
                "detail": investigation.outcome or "",
            }
        )

    events.sort(key=lambda e: e["at"])
    return events


def build_detail(db: Session, investigation: Investigation) -> Dict[str, Any]:
    """Full workspace payload: alerts, transactions, network, factors, timeline."""
    from app.services.alert_service import to_list_item

    customer = investigation.customer
    alerts: List[Dict[str, Any]] = []
    if customer:
        rows = db.scalars(
            select(Alert)
            .where(Alert.customer_id == customer.id)
            .order_by(Alert.raised_at.desc())
            .limit(20)
        ).all()
        alerts = [to_list_item(a) for a in rows]
    elif investigation.alert:
        alerts = [to_list_item(investigation.alert)]

    # Latest explainable assessment drives the risk-factor panel
    risk_factors: List[Dict[str, Any]] = []
    if customer:
        latest = db.scalar(
            select(RiskAssessment)
            .where(RiskAssessment.customer_id == customer.id)
            .order_by(RiskAssessment.assessed_at.desc())
            .limit(1)
        )
        if latest and latest.factors:
            risk_factors = latest.factors

    linked_transactions: List[Dict[str, Any]] = []
    if customer and customer.accounts:
        account_ids = [a.id for a in customer.accounts]
        rows = db.scalars(
            select(Transaction)
            .where(
                (Transaction.sender_account_id.in_(account_ids))
                | (Transaction.receiver_account_id.in_(account_ids))
            )
            .order_by(Transaction.occurred_at.desc())
            .limit(25)
        ).all()
        owned = set(account_ids)
        linked_transactions = [
            {
                "txn_ref": t.txn_ref,
                "occurred_at": t.occurred_at.isoformat(),
                "amount": t.amount,
                "currency": t.currency,
                "channel": t.channel,
                "direction": "OUT" if t.sender_account_id in owned else "IN",
                "risk_score": t.risk_score,
                "risk_level": t.risk_level,
                "status": t.status,
                "has_alert": t.has_alert,
            }
            for t in rows
        ]
    elif investigation.network_id:
        rows = db.scalars(
            select(Transaction)
            .where(Transaction.network_id == investigation.network_id)
            .order_by(Transaction.occurred_at.desc())
            .limit(25)
        ).all()
        linked_transactions = [
            {
                "txn_ref": t.txn_ref,
                "occurred_at": t.occurred_at.isoformat(),
                "amount": t.amount,
                "currency": t.currency,
                "channel": t.channel,
                "direction": "OUT",
                "risk_score": t.risk_score,
                "risk_level": t.risk_level,
                "status": t.status,
                "has_alert": t.has_alert,
            }
            for t in rows
        ]

    network_snapshot: Optional[Dict[str, Any]] = None
    if investigation.network:
        graph = network_service.network_graph(db, investigation.network)
        network_snapshot = {
            "network_ref": graph["network_ref"],
            "stats": graph["stats"],
            "nodes": [n.model_dump() for n in graph["nodes"]],
            "edges": [e.model_dump() for e in graph["edges"]],
            "assessment": graph["assessment"].model_dump() if graph["assessment"] else None,
        }

    return {
        "alerts": alerts,
        "risk_factors": risk_factors,
        "linked_transactions": linked_transactions,
        "network_snapshot": network_snapshot,
        "timeline": build_timeline(db, investigation),
        "advisory": INVESTIGATION_ADVISORY,
    }


def to_list_item(db: Session, investigation: Investigation) -> Dict[str, Any]:
    note_count = int(
        db.scalar(
            select(func.count(InvestigationNote.id)).where(
                InvestigationNote.investigation_id == investigation.id
            )
        )
        or 0
    )
    return {
        "id": investigation.id,
        "case_ref": investigation.case_ref,
        "title": investigation.title,
        "status": investigation.status,
        "priority": investigation.priority,
        "risk_score": investigation.risk_score,
        "opened_at": investigation.opened_at,
        "due_at": investigation.due_at,
        "closed_at": investigation.closed_at,
        "outcome": investigation.outcome,
        "customer_ref": investigation.customer.customer_ref if investigation.customer else None,
        "customer_name": investigation.customer.name if investigation.customer else None,
        "alert_ref": investigation.alert.alert_ref if investigation.alert else None,
        "network_ref": investigation.network.network_ref if investigation.network else None,
        "assignee_name": investigation.assignee.full_name if investigation.assignee else None,
        "note_count": note_count,
    }


def active_count(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count(Investigation.id)).where(
                Investigation.status.notin_(list(_CLOSED))
            )
        )
        or 0
    )
