"""Alert, investigation and audit schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class AlertListItem(ORMModel):
    id: int
    alert_ref: str
    source: str
    alert_type: str
    title: str
    rule_code: Optional[str] = None
    risk_score: float
    risk_level: str
    severity: str
    status: str
    raised_at: datetime
    customer_ref: Optional[str] = None
    customer_name: Optional[str] = None
    transaction_ref: Optional[str] = None
    network_ref: Optional[str] = None
    assignee_name: Optional[str] = None


class AlertDetail(AlertListItem):
    explanation: str
    evidence: Dict[str, Any] = {}
    disposition_note: Optional[str] = None
    closed_at: Optional[datetime] = None
    investigation_ref: Optional[str] = None
    advisory: str = ""


class AlertStatusUpdate(BaseModel):
    status: str = Field(
        pattern="^(NEW|UNDER_REVIEW|ESCALATED|CLEARED|CONFIRMED_SUSPICIOUS)$"
    )
    note: Optional[str] = Field(default=None, max_length=2000)


class AlertAssignRequest(BaseModel):
    assignee_username: str = Field(min_length=3, max_length=64)


class ReactivePatternCard(BaseModel):
    """One reactive detection, presented as a narrative for investigators."""

    alert_ref: str
    pattern_code: str
    pattern_name: str
    customer_ref: Optional[str]
    customer_name: Optional[str]
    severity: str
    risk_score: float
    risk_level: str
    status: str
    raised_at: datetime
    headline: str
    explanation: str
    metrics: List[Dict[str, Any]] = []
    transaction_refs: List[str] = []


class ReactiveOverview(BaseModel):
    window_label: str
    total_alerts: int
    open_alerts: int
    pattern_counts: Dict[str, int]
    cards: List[ReactivePatternCard]
    advisory: str


# ---------------------------------------------------------------------------
# Investigations
# ---------------------------------------------------------------------------


class NoteOut(ORMModel):
    id: int
    author_name: str
    note_type: str
    body: str
    created_at: datetime


class InvestigationListItem(ORMModel):
    id: int
    case_ref: str
    title: str
    status: str
    priority: str
    risk_score: float
    opened_at: datetime
    due_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    outcome: Optional[str] = None
    customer_ref: Optional[str] = None
    customer_name: Optional[str] = None
    alert_ref: Optional[str] = None
    network_ref: Optional[str] = None
    assignee_name: Optional[str] = None
    note_count: int = 0


class TimelineEvent(BaseModel):
    at: datetime
    actor: str
    kind: str
    label: str
    detail: str = ""


class InvestigationDetail(InvestigationListItem):
    summary: Optional[str] = ""
    notes: List[NoteOut] = []
    timeline: List[TimelineEvent] = []
    alerts: List[AlertListItem] = []
    risk_factors: List[Dict[str, Any]] = []
    linked_transactions: List[Dict[str, Any]] = []
    network_snapshot: Optional[Dict[str, Any]] = None
    advisory: str = ""


class InvestigationCreate(BaseModel):
    title: str = Field(min_length=4, max_length=200)
    alert_ref: Optional[str] = Field(default=None, max_length=32)
    customer_ref: Optional[str] = Field(default=None, max_length=32)
    network_ref: Optional[str] = Field(default=None, max_length=32)
    priority: str = Field(default="MEDIUM", pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    summary: Optional[str] = Field(default="", max_length=4000)


class InvestigationNoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    note_type: str = Field(default="NOTE", pattern="^(NOTE|ESCALATION|SYSTEM)$")


class InvestigationStatusUpdate(BaseModel):
    status: str = Field(
        pattern="^(OPEN|IN_PROGRESS|PENDING_APPROVAL|CLOSED_CLEARED|CLOSED_REPORTED)$"
    )
    outcome: Optional[str] = Field(default=None, max_length=48)
    note: Optional[str] = Field(default=None, max_length=2000)


class InvestigationAssignRequest(BaseModel):
    assignee_username: str = Field(min_length=3, max_length=64)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class AuditLogItem(ORMModel):
    id: int
    occurred_at: datetime
    actor: str
    actor_role: str
    action: str
    resource_type: str
    resource_ref: str
    previous_state: Optional[str] = None
    new_state: Optional[str] = None
    detail: Optional[str] = None
    ip_address: str
    session_id: str
