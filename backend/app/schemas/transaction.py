"""Transaction, gateway and decision-pipeline schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ModelProvenance, ORMModel, RiskFactor


class TransactionListItem(ORMModel):
    id: int
    txn_ref: str
    occurred_at: datetime
    amount: float
    currency: str
    channel: str
    txn_type: str
    status: str
    city: str
    country: str
    is_international: bool
    risk_score: float
    risk_level: str
    decision: str
    integrity_status: str
    has_alert: bool
    scored_by: str
    sender_ref: str = ""
    sender_name: str = ""
    receiver_ref: str = ""
    receiver_name: str = ""
    network_ref: Optional[str] = None


class TransactionDetail(TransactionListItem):
    narrative: Optional[str] = None
    device_fingerprint: Optional[str] = None
    claimed_amount: Optional[float] = None
    triggered_rules: List[str] = []
    order_ref: Optional[str] = None
    sender_customer_ref: Optional[str] = None
    receiver_customer_ref: Optional[str] = None
    is_suspicious_edge: bool = False
    risk_factors: List[RiskFactor] = []
    peer_context: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Transaction integrity gateway
# ---------------------------------------------------------------------------


class PaymentIntentRequest(BaseModel):
    """What an (untrusted) client sends to request payment creation.

    `claimed_amount` exists ONLY so the gateway can compare it against the
    server-side authoritative order amount. It is never used as the amount.
    """

    order_ref: str = Field(min_length=3, max_length=32)
    claimed_amount: float = Field(gt=0, le=1_000_000_000)
    claimed_currency: str = Field(default="INR", min_length=3, max_length=8)
    customer_ref: Optional[str] = Field(default=None, max_length=32)
    channel: str = Field(default="UPI", max_length=16)
    device_fingerprint: Optional[str] = Field(default=None, max_length=64)
    idempotency_key: Optional[str] = Field(default=None, max_length=64)

    @field_validator("claimed_currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return value.upper()


class IntegrityCheck(BaseModel):
    """Outcome of comparing the client request against server-side truth."""

    status: str
    passed: bool
    order_ref: str
    # The authoritative value, read from the orders table
    authorized_amount: float
    authorized_currency: str
    received_amount: float
    received_currency: str
    mismatch_amount: float
    mismatch_pct: float
    digest_valid: bool
    message: str
    # Explicit statement of which side is trusted
    source_of_truth: str = "server:orders.authorized_amount"


class PipelineStep(BaseModel):
    key: str
    label: str
    # PASS | WARN | FAIL | SKIPPED
    status: str
    detail: str = ""
    value: Optional[str] = None
    duration_ms: float = 0.0


class GatewayDecision(BaseModel):
    """The full pre-transaction decision, step by step."""

    request_id: str
    order_ref: str
    customer_ref: Optional[str] = None
    decision: str
    risk_score: float
    risk_level: str
    integrity: IntegrityCheck
    pipeline: List[PipelineStep]
    factors: List[RiskFactor]
    features: Dict[str, Any] = {}
    triggered_rules: List[str] = []
    provenance: ModelProvenance
    # Only populated when the payment was actually allowed to settle
    transaction_ref: Optional[str] = None
    alert_ref: Optional[str] = None
    # The amount that would be sent onward - always the authorized one
    amount_forwarded: Optional[float] = None
    payment_provider_note: str
    advisory: str
    evaluated_at: datetime


class TransactionAnalyzeRequest(BaseModel):
    """Score a hypothetical transaction without creating it."""

    customer_ref: str = Field(min_length=3, max_length=32)
    amount: float = Field(gt=0, le=1_000_000_000)
    channel: str = Field(default="UPI", max_length=16)
    receiver_account_ref: Optional[str] = Field(default=None, max_length=32)
    country: str = Field(default="India", max_length=64)


class TransactionAnalyzeResponse(BaseModel):
    customer_ref: str
    risk_score: float
    risk_level: str
    decision: str
    model_probability: Optional[float]
    factors: List[RiskFactor]
    features: Dict[str, Any]
    triggered_rules: List[str]
    provenance: ModelProvenance
    advisory: str


class OrderSummary(ORMModel):
    id: int
    order_ref: str
    merchant_name: str
    description: str
    authorized_amount: float
    currency: str
    status: str
    created_at: datetime
    customer_ref: str = ""
    customer_name: str = ""
