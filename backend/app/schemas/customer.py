"""Customer, account and behavioural-profile schemas."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.schemas.common import ModelProvenance, ORMModel, RiskFactor, TimePoint


class AccountSummary(ORMModel):
    id: int
    account_ref: str
    display_name: str
    entity_type: str
    institution: str
    currency: str
    country: str
    city: str
    balance: float
    is_internal: bool
    is_dormant: bool
    risk_score: float
    risk_level: str
    total_in: float
    total_out: float
    degree_in: int
    degree_out: int


class CustomerListItem(ORMModel):
    id: int
    customer_ref: str
    name: str
    city: str
    country: str
    account_age_years: float
    kyc_level: str
    pep_flag: bool
    current_risk_score: float
    current_risk_level: str
    risk_trend: str
    under_monitoring: bool
    previous_alert_count: int


class BehaviouralStats(BaseModel):
    """The behavioural aggregates shown on the customer profile."""

    avg_transaction_amount: float
    median_transaction_amount: float
    max_transaction_amount: float
    transactions_per_month: float
    total_transactions: int
    unique_counterparties: int
    new_counterparties_30d: int
    international_share: float
    velocity_label: str
    velocity_max_per_hour: int
    previous_alerts: int
    total_outflow: float
    total_inflow: float
    baseline_avg_amount: float
    amount_deviation_ratio: float


class CustomerDetail(CustomerListItem):
    email: Optional[str] = None
    phone: Optional[str] = None
    occupation: Optional[str] = None
    onboarded_on: date
    entity_type: str
    risk_country_exposure: float
    baseline_avg_amount: float
    baseline_monthly_count: float
    baseline_counterparties: int
    accounts: List[AccountSummary] = []
    behaviour: Optional[BehaviouralStats] = None


class RiskTrajectoryPoint(BaseModel):
    label: str
    period_start: datetime
    risk_score: float
    risk_level: str


class CustomerRiskProfile(BaseModel):
    """Full proactive risk explanation for one customer."""

    customer_ref: str
    name: str
    risk_score: float
    risk_level: str
    trend: str
    decision: str
    assessed_at: datetime
    model_probability: Optional[float] = None
    provenance: ModelProvenance
    factors: List[RiskFactor]
    features: Dict[str, Any]
    trajectory: List[RiskTrajectoryPoint]
    behaviour: BehaviouralStats
    triggered_rules: List[str] = []
    # Standing disclaimer surfaced next to every score
    advisory: str


class ProactiveWatchlistItem(BaseModel):
    customer_ref: str
    name: str
    risk_score: float
    risk_level: str
    trend: str
    delta_30d: float
    top_factor: str
    monitored: bool


class ProactiveOverview(BaseModel):
    total_monitored: int
    escalating_count: int
    avg_risk_score: float
    band_counts: Dict[str, int]
    watchlist: List[ProactiveWatchlistItem]
    portfolio_trend: List[TimePoint]
    advisory: str
