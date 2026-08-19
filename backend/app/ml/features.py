"""Feature contract for the proactive behavioural risk model.

`FEATURE_SPEC` is the single source of truth for the model's input space. The
trainer, the live feature extractor, the explanation layer and the Model
Insights page all read from it, so a feature can never silently drift out of
sync between training and inference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence

import numpy as np


@dataclass(frozen=True)
class FeatureDef:
    name: str
    label: str
    description: str
    # Family used to group factors in the UI
    category: str = "BEHAVIOURAL"
    # Plain-language unit, used when rendering the factor detail line
    unit: str = ""
    # Value used as the neutral baseline when computing occlusion attributions
    baseline: float = 0.0
    # Clamp applied before the model sees the value, to keep tails bounded
    clip: tuple[float, float] = (0.0, 1e9)


FEATURE_SPEC: List[FeatureDef] = [
    FeatureDef(
        name="amount_deviation_ratio",
        label="Amount vs historical average",
        description=(
            "Current transaction amount divided by the customer's own trailing "
            "average. 1.0 means perfectly in line with their history."
        ),
        category="BEHAVIOURAL",
        unit="x baseline",
        baseline=1.0,
        clip=(0.0, 60.0),
    ),
    FeatureDef(
        name="amount_log",
        label="Transaction amount (log)",
        description="Natural log of the transaction amount, so scale matters but does not dominate.",
        category="BEHAVIOURAL",
        unit="log INR",
        baseline=9.2,
        clip=(0.0, 25.0),
    ),
    FeatureDef(
        name="txn_count_30d",
        label="Transactions in last 30 days",
        description="Recent activity volume for the customer.",
        category="VELOCITY",
        unit="transactions",
        baseline=12.0,
        clip=(0.0, 2000.0),
    ),
    FeatureDef(
        name="frequency_ratio",
        label="Frequency vs baseline",
        description="Recent monthly transaction count divided by the customer's established monthly baseline.",
        category="VELOCITY",
        unit="x baseline",
        baseline=1.0,
        clip=(0.0, 40.0),
    ),
    FeatureDef(
        name="velocity_per_hour",
        label="Peak transactions per hour",
        description="Highest number of transactions the customer executed inside any single hour in the window.",
        category="VELOCITY",
        unit="txn/hour",
        baseline=1.0,
        clip=(0.0, 200.0),
    ),
    FeatureDef(
        name="burst_score",
        label="Burst concentration",
        description=(
            "Share of the window's transactions that fall inside its busiest "
            "15-minute slice. High values indicate bursty, machine-like activity."
        ),
        category="VELOCITY",
        unit="ratio",
        baseline=0.1,
        clip=(0.0, 1.0),
    ),
    FeatureDef(
        name="unique_counterparties_30d",
        label="Unique counterparties (30d)",
        description="Distinct accounts transacted with in the recent window.",
        category="NETWORK",
        unit="accounts",
        baseline=4.0,
        clip=(0.0, 500.0),
    ),
    FeatureDef(
        name="new_counterparties_30d",
        label="New counterparties (30d)",
        description="Counterparties seen for the first time inside the recent window.",
        category="NETWORK",
        unit="accounts",
        baseline=1.0,
        clip=(0.0, 500.0),
    ),
    FeatureDef(
        name="counterparty_growth_ratio",
        label="Counterparty growth",
        description="Recent unique counterparties divided by the customer's historical counterparty baseline.",
        category="NETWORK",
        unit="x baseline",
        baseline=1.0,
        clip=(0.0, 40.0),
    ),
    FeatureDef(
        name="rapid_movement_score",
        label="Rapid movement of funds",
        description=(
            "Fraction of inbound value that leaves the account again within a "
            "short window. Near 1.0 means the account behaves as a pass-through."
        ),
        category="BEHAVIOURAL",
        unit="ratio",
        baseline=0.15,
        clip=(0.0, 1.0),
    ),
    FeatureDef(
        name="structuring_score",
        label="Threshold-adjacent structuring",
        description=(
            "Share of transactions sitting just below a reporting threshold, a "
            "classic structuring signature."
        ),
        category="BEHAVIOURAL",
        unit="ratio",
        baseline=0.05,
        clip=(0.0, 1.0),
    ),
    FeatureDef(
        name="round_amount_ratio",
        label="Round-amount ratio",
        description="Share of transactions with suspiciously round values.",
        category="BEHAVIOURAL",
        unit="ratio",
        baseline=0.2,
        clip=(0.0, 1.0),
    ),
    FeatureDef(
        name="international_share",
        label="Cross-border share",
        description="Share of the customer's recent transactions that are international.",
        category="GEO",
        unit="ratio",
        baseline=0.05,
        clip=(0.0, 1.0),
    ),
    FeatureDef(
        name="high_risk_geo_exposure",
        label="Higher-risk jurisdiction exposure",
        description="Share of value touching jurisdictions on the platform's elevated-risk list.",
        category="GEO",
        unit="ratio",
        baseline=0.0,
        clip=(0.0, 1.0),
    ),
    FeatureDef(
        name="account_age_years",
        label="Relationship age",
        description="Years since onboarding. Younger relationships carry less behavioural context.",
        category="KYC",
        unit="years",
        baseline=4.0,
        clip=(0.0, 40.0),
    ),
    FeatureDef(
        name="previous_alert_count",
        label="Prior alerts",
        description="Number of AML alerts previously raised on this customer.",
        category="KYC",
        unit="alerts",
        baseline=0.0,
        clip=(0.0, 100.0),
    ),
    FeatureDef(
        name="dormancy_reactivation",
        label="Dormancy reactivation",
        description="1.0 when a long-dormant relationship suddenly resumed high-value activity.",
        category="BEHAVIOURAL",
        unit="flag",
        baseline=0.0,
        clip=(0.0, 1.0),
    ),
    FeatureDef(
        name="pep_flag",
        label="Politically exposed person",
        description="KYC flag requiring enhanced due diligence.",
        category="KYC",
        unit="flag",
        baseline=0.0,
        clip=(0.0, 1.0),
    ),
]

FEATURE_NAMES: List[str] = [f.name for f in FEATURE_SPEC]
FEATURE_INDEX: Dict[str, int] = {name: i for i, name in enumerate(FEATURE_NAMES)}
FEATURE_BY_NAME: Dict[str, FeatureDef] = {f.name: f for f in FEATURE_SPEC}
BASELINE_VECTOR = np.array([f.baseline for f in FEATURE_SPEC], dtype=np.float64)

# Features where a HIGHER value means LOWER risk. Used so the explanation layer
# never reports "long-standing relationship" as an aggravating factor.
INVERSE_FEATURES = {"account_age_years"}


def clip_features(values: Dict[str, float]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for spec in FEATURE_SPEC:
        raw = float(values.get(spec.name, spec.baseline) or 0.0)
        lo, hi = spec.clip
        out[spec.name] = float(min(max(raw, lo), hi))
    return out


def to_vector(values: Dict[str, float]) -> np.ndarray:
    """Dict -> ordered 1-D float array matching FEATURE_SPEC order."""
    clipped = clip_features(values)
    return np.array([clipped[name] for name in FEATURE_NAMES], dtype=np.float64)


def to_matrix(rows: Sequence[Dict[str, float]]) -> np.ndarray:
    if not rows:
        return np.zeros((0, len(FEATURE_SPEC)), dtype=np.float64)
    return np.vstack([to_vector(row) for row in rows])


def describe_value(name: str, value: float) -> str:
    """Render a feature value the way an investigator would read it."""
    spec = FEATURE_BY_NAME.get(name)
    if spec is None:
        return f"{value:.2f}"
    if spec.unit == "flag":
        return "yes" if value >= 0.5 else "no"
    if spec.unit == "ratio":
        return f"{value * 100:.0f}%"
    if spec.unit == "x baseline":
        return f"{value:.1f}x"
    if spec.unit in {"transactions", "accounts", "alerts", "txn/hour"}:
        return f"{value:.0f} {spec.unit}"
    if spec.unit == "years":
        return f"{value:.1f} years"
    if spec.unit == "log INR":
        return f"~INR {np.exp(value):,.0f}"
    return f"{value:.2f}"


@dataclass
class FeatureBundle:
    """Extracted features plus the human-readable context behind them."""

    values: Dict[str, float] = field(default_factory=dict)
    context: Dict[str, float] = field(default_factory=dict)

    def vector(self) -> np.ndarray:
        return to_vector(self.values)

    def as_dict(self) -> Dict[str, float]:
        return clip_features(self.values)
