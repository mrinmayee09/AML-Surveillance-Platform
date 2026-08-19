"""Default AML rule catalogue.

Rules are seeded into the `rules` table and evaluated from there, so an admin can
retune a threshold or disable a rule at runtime without touching code. Each entry
declares which feature it reads, which layer consumes it, and how many points it
contributes to the composite score when it fires.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class RuleDefinition:
    code: str
    name: str
    description: str
    category: str
    severity: str
    layer: str  # PROACTIVE | REACTIVE | NETWORK | INTEGRITY
    # Name of the feature (or derived metric) the rule compares against
    feature: str
    operator: str  # GT | GTE | LT | LTE | EQ
    threshold: float
    threshold_unit: str
    score_weight: float
    enabled: bool = True
    params: Dict[str, Any] = field(default_factory=dict)
    # Template rendered into the alert/factor explanation. `{value}` is the
    # observed value, `{threshold}` the configured limit.
    explanation: str = ""


RULE_DEFINITIONS: List[RuleDefinition] = [
    # --- Amount / behavioural -------------------------------------------
    RuleDefinition(
        code="AMOUNT_THRESHOLD",
        name="Transaction amount threshold",
        description=(
            "Flags a single transaction whose value exceeds the configured "
            "reporting threshold for the customer segment."
        ),
        category="AMOUNT",
        severity="MEDIUM",
        layer="PROACTIVE",
        feature="amount",
        operator="GTE",
        threshold=1_000_000.0,
        threshold_unit="INR",
        score_weight=12.0,
        explanation="Transaction value of INR {value} exceeds the INR {threshold} reporting threshold.",
    ),
    RuleDefinition(
        code="AMOUNT_DEVIATION",
        name="Amount deviation from customer baseline",
        description=(
            "Compares the transaction against the customer's own trailing average. "
            "A sudden multiple of established behaviour is a core AML signal."
        ),
        category="BEHAVIOURAL",
        severity="HIGH",
        layer="PROACTIVE",
        feature="amount_deviation_ratio",
        operator="GTE",
        threshold=4.0,
        threshold_unit="x baseline",
        score_weight=22.0,
        explanation="Transaction amount is {value}x the customer's historical average (limit {threshold}x).",
    ),
    RuleDefinition(
        code="BEHAVIOURAL_DEVIATION",
        name="Significant behavioural deviation",
        description=(
            "Composite drift measure across amount, frequency and counterparty "
            "profile versus the customer's established pattern."
        ),
        category="BEHAVIOURAL",
        severity="HIGH",
        layer="REACTIVE",
        feature="behaviour_drift",
        operator="GTE",
        threshold=2.5,
        threshold_unit="drift index",
        score_weight=18.0,
        explanation="Composite behavioural drift index of {value} exceeds the {threshold} tolerance.",
    ),
    # --- Velocity --------------------------------------------------------
    RuleDefinition(
        code="VELOCITY_THRESHOLD",
        name="Transaction velocity threshold",
        description=(
            "Flags an abnormal number of transactions inside a short window, "
            "which can indicate automated or coordinated activity."
        ),
        category="VELOCITY",
        severity="HIGH",
        layer="PROACTIVE",
        feature="velocity_per_hour",
        operator="GTE",
        threshold=8.0,
        threshold_unit="txn/hour",
        score_weight=18.0,
        params={"window_minutes": 60},
        explanation="{value} transactions in a single hour exceeds the {threshold}/hour velocity limit.",
    ),
    RuleDefinition(
        code="FREQUENCY_SPIKE",
        name="Unusual transaction frequency",
        description="Recent monthly transaction count against the customer's own baseline.",
        category="VELOCITY",
        severity="MEDIUM",
        layer="PROACTIVE",
        feature="frequency_ratio",
        operator="GTE",
        threshold=2.5,
        threshold_unit="x baseline",
        score_weight=16.0,
        explanation="Transaction frequency is {value}x the customer's baseline (limit {threshold}x).",
    ),
    RuleDefinition(
        code="BURST_ACTIVITY",
        name="Burst activity concentration",
        description=(
            "Share of activity concentrated in the busiest 15-minute slice. "
            "High concentration suggests scripted rather than human behaviour."
        ),
        category="VELOCITY",
        severity="MEDIUM",
        layer="REACTIVE",
        feature="burst_score",
        operator="GTE",
        threshold=0.45,
        threshold_unit="ratio",
        score_weight=10.0,
        params={"window_minutes": 15},
        explanation="{value} of recent activity falls inside one 15-minute window (limit {threshold}).",
    ),
    # --- Rapid movement --------------------------------------------------
    RuleDefinition(
        code="RAPID_FUND_MOVEMENT",
        name="Rapid movement of funds",
        description=(
            "Detects value forwarded onward almost immediately after receipt - "
            "the defining characteristic of a pass-through or mule account."
        ),
        category="BEHAVIOURAL",
        severity="CRITICAL",
        layer="REACTIVE",
        feature="rapid_movement_score",
        operator="GTE",
        threshold=0.7,
        threshold_unit="ratio",
        score_weight=20.0,
        params={"window_minutes": 30},
        explanation="{value} of inbound value was forwarded onward within 30 minutes (limit {threshold}).",
    ),
    RuleDefinition(
        code="STRUCTURING",
        name="Threshold-adjacent structuring",
        description=(
            "Repeated transactions sitting just below a reporting threshold, "
            "consistent with deliberate structuring to avoid reporting."
        ),
        category="BEHAVIOURAL",
        severity="HIGH",
        layer="REACTIVE",
        feature="structuring_score",
        operator="GTE",
        threshold=0.35,
        threshold_unit="ratio",
        score_weight=17.0,
        explanation="{value} of transactions sit just below the reporting threshold (limit {threshold}).",
    ),
    # --- Counterparties --------------------------------------------------
    RuleDefinition(
        code="NEW_BENEFICIARY",
        name="New beneficiary activity",
        description=(
            "Counts beneficiaries seen for the first time in the recent window. "
            "A burst of new payees often precedes dispersion of funds."
        ),
        category="NETWORK",
        severity="MEDIUM",
        layer="PROACTIVE",
        feature="new_counterparties_30d",
        operator="GTE",
        threshold=5.0,
        threshold_unit="accounts",
        score_weight=15.0,
        params={"window_days": 30},
        explanation="{value} new beneficiaries detected in 30 days (limit {threshold}).",
    ),
    RuleDefinition(
        code="MULTIPLE_COUNTERPARTIES",
        name="Multiple counterparties",
        description="Growth in distinct counterparties relative to the customer's norm.",
        category="NETWORK",
        severity="MEDIUM",
        layer="REACTIVE",
        feature="counterparty_growth_ratio",
        operator="GTE",
        threshold=3.0,
        threshold_unit="x baseline",
        score_weight=14.0,
        explanation="Counterparty count is {value}x the customer's baseline (limit {threshold}x).",
    ),
    # --- Geography -------------------------------------------------------
    RuleDefinition(
        code="GEOGRAPHIC_RISK",
        name="Higher-risk jurisdiction exposure",
        description=(
            "Share of value touching jurisdictions on the platform's elevated-risk "
            "list. Configurable per institution policy."
        ),
        category="GEO",
        severity="HIGH",
        layer="PROACTIVE",
        feature="high_risk_geo_exposure",
        operator="GTE",
        threshold=0.25,
        threshold_unit="ratio",
        score_weight=14.0,
        explanation="{value} of value touches an elevated-risk jurisdiction (limit {threshold}).",
    ),
    RuleDefinition(
        code="CROSS_BORDER_SHARE",
        name="Cross-border concentration",
        description="Proportion of activity that is international.",
        category="GEO",
        severity="LOW",
        layer="REACTIVE",
        feature="international_share",
        operator="GTE",
        threshold=0.5,
        threshold_unit="ratio",
        score_weight=8.0,
        explanation="{value} of recent activity is cross-border (limit {threshold}).",
    ),
    # --- KYC -------------------------------------------------------------
    RuleDefinition(
        code="ACCOUNT_AGE",
        name="Young account, high value",
        description=(
            "A recently opened relationship transacting at material value has "
            "little behavioural history to validate against."
        ),
        category="KYC",
        severity="MEDIUM",
        layer="PROACTIVE",
        feature="account_age_years",
        operator="LTE",
        threshold=1.0,
        threshold_unit="years",
        score_weight=11.0,
        explanation="Relationship is only {value} old (threshold {threshold}), limiting behavioural context.",
    ),
    RuleDefinition(
        code="PRIOR_ALERTS",
        name="Prior alert history",
        description="Customer has existing AML alerts on file.",
        category="KYC",
        severity="MEDIUM",
        layer="PROACTIVE",
        feature="previous_alert_count",
        operator="GTE",
        threshold=2.0,
        threshold_unit="alerts",
        score_weight=10.0,
        explanation="{value} prior alerts on this customer (threshold {threshold}).",
    ),
    RuleDefinition(
        code="DORMANT_REACTIVATION",
        name="Dormant account reactivation",
        description="A long-inactive relationship resuming high-value activity.",
        category="BEHAVIOURAL",
        severity="HIGH",
        layer="REACTIVE",
        feature="dormancy_reactivation",
        operator="GTE",
        threshold=1.0,
        threshold_unit="flag",
        score_weight=13.0,
        explanation="Dormant relationship resumed high-value activity.",
    ),
    # --- Network ---------------------------------------------------------
    RuleDefinition(
        code="NETWORK_CIRCULAR_FLOW",
        name="Circular fund flow",
        description=(
            "Structural rule: value returns toward an account it previously left, "
            "after passing through intermediaries."
        ),
        category="NETWORK",
        severity="CRITICAL",
        layer="NETWORK",
        feature="network_circular",
        operator="GTE",
        threshold=1.0,
        threshold_unit="flag",
        score_weight=22.0,
        explanation="Circular flow detected across {value} accounts.",
    ),
    RuleDefinition(
        code="NETWORK_LAYERING",
        name="Layered intermediary movement",
        description=(
            "Structural rule: funds relayed through a chain of accounts that "
            "retain almost none of the value."
        ),
        category="NETWORK",
        severity="CRITICAL",
        layer="NETWORK",
        feature="network_layering",
        operator="GTE",
        threshold=2.0,
        threshold_unit="intermediaries",
        score_weight=20.0,
        explanation="{value} chained intermediary accounts detected in the flow path.",
    ),
    RuleDefinition(
        code="NETWORK_FAN_PATTERN",
        name="Fan-out / fan-in dispersion",
        description=(
            "Structural rule: one account distributing to or collecting from many "
            "counterparties with uniform amounts in a short window."
        ),
        category="NETWORK",
        severity="HIGH",
        layer="NETWORK",
        feature="network_fan_degree",
        operator="GTE",
        threshold=5.0,
        threshold_unit="counterparties",
        score_weight=16.0,
        explanation="Account transacted with {value} counterparties in a single burst.",
    ),
    # --- Integrity -------------------------------------------------------
    RuleDefinition(
        code="INTEGRITY_AMOUNT_MISMATCH",
        name="Payment amount integrity mismatch",
        description=(
            "The amount in an incoming payment request does not match the "
            "server-authorised order amount. Any mismatch blocks the payment."
        ),
        category="INTEGRITY",
        severity="CRITICAL",
        layer="INTEGRITY",
        feature="amount_mismatch",
        operator="GT",
        threshold=0.0,
        threshold_unit="INR",
        score_weight=100.0,
        explanation="Client requested INR {value} against a server-authorised amount that differs.",
    ),
    RuleDefinition(
        code="INTEGRITY_DIGEST_INVALID",
        name="Order integrity digest invalid",
        description=(
            "The stored order row failed its HMAC integrity check, indicating the "
            "order record itself may have been altered."
        ),
        category="INTEGRITY",
        severity="CRITICAL",
        layer="INTEGRITY",
        feature="digest_invalid",
        operator="GTE",
        threshold=1.0,
        threshold_unit="flag",
        score_weight=100.0,
        explanation="Order integrity digest verification failed.",
    ),
]

RULES_BY_CODE = {r.code: r for r in RULE_DEFINITIONS}
