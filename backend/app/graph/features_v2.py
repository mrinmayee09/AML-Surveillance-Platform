"""Graph feature schema for the reactive GNN - the single source of truth.

Training (IBM AMLworld) and live inference (the platform database) both
featurise through the pure functions in this module, so the two cannot drift.

Design rules
------------
* An account's features describe its activity across the WHOLE source inside
  the time window, not only the edges of whatever subgraph is being scored, so
  an account has one feature vector per window whichever neighbourhood it is
  viewed in. (v1 re-featurised every subgraph, so scores changed with the view.)
* Dataset-neutral. Money is in one reference currency (USD), payment channels
  map onto a shared vocabulary of payment rails, and profile (KYC) features are
  optional - AMLworld has none. The `FeatureSchema` a model was trained with is
  stored in its checkpoint and reused at inference, so an AMLworld-trained model
  is always fed exactly the columns it learned from.

Nothing here touches the database. Inputs are plain `TransferRecord` /
`AccountProfile` values produced by `app.graph.db_source`,
`app.graph.columnar_source` (AMLworld) or tests.

Changelog
---------
2.0  R1: institution-wide window features, ego marker, time-ordering edge flags.
2.1  R2: reference currency (USD), shared payment rails, optional profile block,
     cross-institution flag and share.
"""

from __future__ import annotations

import bisect
import math
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

FEATURE_SCHEMA_VERSION = "2.1"
REFERENCE_CURRENCY = "USD"

# Platform jurisdiction (India): cash-transaction reporting threshold in INR and
# the band below it treated as structuring. Shared with the proactive layer
# (`app.services.feature_service`) and used by the database source to flag
# near-threshold transfers on their ORIGINAL amount.
PLATFORM_REPORTING_THRESHOLD = 1_000_000.0
STRUCTURING_BAND = (0.80, 0.999)

# Conversion used for platform (database) transfers. AMLworld derives its own
# rates from the data (`app.datasets.amlworld`). Demo-grade, fixed rate.
PLATFORM_FX_TO_REFERENCE: Dict[str, float] = {"USD": 1.0, "INR": 1.0 / 83.0}

# Money is log-normalised; the scale keeps typical values roughly in [0, 1]
_MONEY_LOG_SCALE = 20.0
_COUNT_LOG_CAP = math.log1p(500)
_PARTNER_LOG_CAP = math.log1p(200)
_BURST_LOG_CAP = math.log1p(50)
_AGE_LOG_CAP = math.log1p(3650)

# A transfer forwarded within this long of funds arriving counts as rapid relay
RAPID_RELAY = timedelta(minutes=60)
_BURST_WINDOW = timedelta(minutes=60)


# ---------------------------------------------------------------------------
# Payment rails: one vocabulary for every dataset
# ---------------------------------------------------------------------------

RAILS = (
    "INSTANT",  # real-time account-to-account: UPI, IMPS
    "BATCH",  # batched clearing: NEFT, ACH
    "WIRE",  # high-value gross settlement: RTGS, wire
    "CARD",
    "CASH",
    "CHEQUE",
    "CRYPTO",
    "REINVESTMENT",
    "WALLET",
)
RAIL_ALIASES: Dict[str, str] = {
    "UPI": "INSTANT",
    "IMPS": "INSTANT",
    "NEFT": "BATCH",
    "ACH": "BATCH",
    "RTGS": "WIRE",
    "WIRE": "WIRE",
    "CARD": "CARD",
    "CREDIT CARD": "CARD",
    "CASH": "CASH",
    "CHEQUE": "CHEQUE",
    "CHECK": "CHEQUE",
    "BITCOIN": "CRYPTO",
    "CRYPTO": "CRYPTO",
    "REINVESTMENT": "REINVESTMENT",
    "WALLET": "WALLET",
}


def payment_rail(channel: Optional[str]) -> str:
    """Map a dataset-specific channel name onto the shared rail vocabulary."""
    return RAIL_ALIASES.get((channel or "").strip().upper(), "OTHER")


@dataclass(frozen=True)
class WindowConfig:
    """Shape of the unit the GNN is trained on and scored on."""

    days: int = 7
    # Matches the encoder's 3 message-passing layers, so the seed's receptive
    # field ends inside the window rather than past its edge.
    hops: int = 3
    max_nodes: int = 300
    max_edges: int = 4000
    # Accounts with more distinct counterparties than this in the window (merchant
    # tills, payroll hubs) are included but not expanded through, otherwise one
    # hub drags hundreds of unrelated customers into every neighbourhood.
    hub_partner_limit: int = 50

    @property
    def span(self) -> timedelta:
        return timedelta(days=self.days)


# ---------------------------------------------------------------------------
# Input records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TransferRecord:
    """One settled transfer.

    `amount` is in the reference currency; `occurred_at` is timezone-aware UTC.
    Round-value and near-threshold are properties of the ORIGINAL amount in its
    own currency and jurisdiction (INR 10,000 is round; its USD value is not), so
    sources set them; `None` falls back to the schema's reference-currency rule.
    """

    key: str
    source: str
    target: str
    amount: float
    occurred_at: datetime
    channel: str = "OTHER"
    is_international: bool = False
    cross_institution: bool = False
    round_amount: Optional[bool] = None
    near_threshold: Optional[bool] = None
    db_id: Optional[int] = None


@dataclass(frozen=True)
class AccountProfile:
    """Slow-changing facts about an account (not derived from the window)."""

    key: str
    entity_type: str = "ACCOUNT"
    is_internal: bool = True
    account_age_days: int = 365
    is_dormant: bool = False
    high_risk_jurisdiction: bool = False
    pep: bool = False
    label: str = ""
    db_id: Optional[int] = None


# ---------------------------------------------------------------------------
# The schema: which columns exist, and the dataset-dependent constants
# ---------------------------------------------------------------------------

_PROFILE_SPEC: List[Tuple[str, str]] = [
    ("type_individual", "Individual account"),
    ("type_merchant", "Merchant account"),
    ("type_company", "Company account"),
    ("type_wallet_or_beneficiary", "Wallet or external beneficiary"),
    ("is_internal", "Held at this institution"),
    ("account_age_norm", "Account age"),
    ("dormant_flag", "Previously dormant"),
    ("high_risk_jurisdiction", "Elevated-risk jurisdiction"),
    ("pep_flag", "Politically exposed person"),
]

_BEHAVIOUR_SPEC: List[Tuple[str, str]] = [
    ("in_count_log", "Inbound transfers"),
    ("out_count_log", "Outbound transfers"),
    ("in_value_log", "Inbound value"),
    ("out_value_log", "Outbound value"),
    ("partners_in_log", "Distinct payers"),
    ("partners_out_log", "Distinct payees"),
    ("pass_through", "Inflow vs outflow balance"),
    ("net_flow", "Net accumulation (+) vs drain (-)"),
    ("rapid_relay_share", "Share of outflow forwarded within an hour of receipt"),
    ("relay_speed", "Speed of onward transfer after receipt"),
    ("amount_cv_norm", "Variability of transfer sizes"),
    ("round_ratio", "Share of round-value transfers"),
    ("near_threshold_ratio", "Share just below the reporting threshold"),
    ("cross_border_share", "Share of value crossing borders / currencies"),
    ("cross_institution_share", "Share of value moving to or from other banks"),
    ("timing_concentration", "Share of activity in the busiest hour"),
    ("burst_log", "Largest one-hour burst"),
    ("active_day_ratio", "Share of window days with activity"),
]

_WINDOW_SPEC: List[Tuple[str, str]] = [
    ("is_seed", "The account this neighbourhood is centred on (ego marker)"),
]

_EDGE_SPEC: List[Tuple[str, str]] = [
    ("amount_log", "Transfer amount"),
    ("round_flag", "Round-value amount"),
    ("near_threshold_flag", "Just below the reporting threshold"),
    ("cross_border_flag", "Crosses a border / currency"),
    ("cross_institution_flag", "Moves between banks"),
    ("share_of_sender_out", "Share of the sender's outflow in the window"),
    ("share_of_receiver_in", "Share of the receiver's inflow in the window"),
    ("has_prior_inbound", "Sender had received funds earlier in the window"),
    ("relay_latency_norm", "Time since the sender last received funds"),
    ("time_to_window_end", "How long before the window end it happened"),
    *[(f"rail_{rail.lower()}", f"{rail.title()} payment rail") for rail in RAILS],
    ("rail_other", "Other / unknown payment rail"),
]


@dataclass(frozen=True)
class FeatureSchema:
    """Everything that decides what a feature vector contains."""

    version: str = FEATURE_SCHEMA_VERSION
    include_profile: bool = True
    reference_currency: str = REFERENCE_CURRENCY
    # Structuring signal: amounts just below this (reference currency)
    reporting_threshold: float = 10_000.0
    structuring_band: Tuple[float, float] = STRUCTURING_BAND

    @property
    def node_spec(self) -> List[Tuple[str, str]]:
        return (_PROFILE_SPEC if self.include_profile else []) + _BEHAVIOUR_SPEC + _WINDOW_SPEC

    @property
    def edge_spec(self) -> List[Tuple[str, str]]:
        return list(_EDGE_SPEC)

    @property
    def node_feature_names(self) -> List[str]:
        return [name for name, _ in self.node_spec]

    @property
    def edge_feature_names(self) -> List[str]:
        return [name for name, _ in self.edge_spec]

    @property
    def node_dim(self) -> int:
        return len(self.node_spec)

    @property
    def account_dim(self) -> int:
        """Account-level columns: everything except the window-relative ones."""
        return self.node_dim - len(_WINDOW_SPEC)

    @property
    def edge_dim(self) -> int:
        return len(_EDGE_SPEC)

    def to_dict(self) -> Dict[str, object]:
        data = asdict(self)
        data["structuring_band"] = list(self.structuring_band)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "FeatureSchema":
        data = dict(data)
        data["structuring_band"] = tuple(data.get("structuring_band", (0.80, 0.999)))
        return cls(**data)


# Platform database: KYC profile available
PLATFORM_SCHEMA = FeatureSchema(include_profile=True)
# IBM AMLworld: transactions only, no account profiles
AMLWORLD_SCHEMA = FeatureSchema(include_profile=False)


# ---------------------------------------------------------------------------
# Per-account window statistics
# ---------------------------------------------------------------------------


@dataclass
class AccountWindowStats:
    """Raw, human-readable measurements of one account inside one window.

    Kept separate from the normalised feature vector so explanations and the UI
    can quote real numbers ("USD 9.8 K forwarded 4 minutes after receipt").
    """

    key: str
    window_start: datetime
    window_end: datetime
    in_count: int = 0
    out_count: int = 0
    in_value: float = 0.0
    out_value: float = 0.0
    partners_in: int = 0
    partners_out: int = 0
    pass_through: float = 0.0
    net_flow: float = 0.0
    rapid_relay_share: float = 0.0
    median_relay_minutes: Optional[float] = None
    amount_cv: float = 0.0
    round_ratio: float = 0.0
    near_threshold_ratio: float = 0.0
    cross_border_share: float = 0.0
    cross_institution_share: float = 0.0
    timing_concentration: float = 0.0
    max_burst: int = 0
    active_days: int = 0
    last_activity_at: Optional[datetime] = None
    # Sorted inbound timestamps - used to compute edge relay latency, not exported
    inbound_times: List[datetime] = field(default_factory=list, repr=False)

    @property
    def partners(self) -> int:
        return self.partners_in + self.partners_out

    def to_dict(self) -> Dict[str, object]:
        """JSON-safe view (for the stats store and API payloads)."""
        return {
            "in_count": self.in_count,
            "out_count": self.out_count,
            "in_value": round(self.in_value, 2),
            "out_value": round(self.out_value, 2),
            "partners_in": self.partners_in,
            "partners_out": self.partners_out,
            "pass_through": round(self.pass_through, 4),
            "net_flow": round(self.net_flow, 4),
            "rapid_relay_share": round(self.rapid_relay_share, 4),
            "median_relay_minutes": (
                round(self.median_relay_minutes, 2)
                if self.median_relay_minutes is not None
                else None
            ),
            "amount_cv": round(self.amount_cv, 4),
            "round_ratio": round(self.round_ratio, 4),
            "near_threshold_ratio": round(self.near_threshold_ratio, 4),
            "cross_border_share": round(self.cross_border_share, 4),
            "cross_institution_share": round(self.cross_institution_share, 4),
            "timing_concentration": round(self.timing_concentration, 4),
            "max_burst": self.max_burst,
            "active_days": self.active_days,
        }


def is_round(amount: float) -> bool:
    """Round-value heuristic: whole multiples of 1k / 10k / 100k (reference currency)."""
    for unit in (100_000, 10_000, 1_000):
        if amount >= unit and abs(amount % unit) < 1e-6:
            return True
    return False


def is_near_threshold(amount: float, schema: FeatureSchema) -> bool:
    lo = schema.reporting_threshold * schema.structuring_band[0]
    hi = schema.reporting_threshold * schema.structuring_band[1]
    return lo <= amount <= hi


def transfer_is_round(t: TransferRecord) -> bool:
    return t.round_amount if t.round_amount is not None else is_round(t.amount)


def transfer_near_threshold(t: TransferRecord, schema: FeatureSchema) -> bool:
    return t.near_threshold if t.near_threshold is not None else is_near_threshold(t.amount, schema)


def in_window(t: datetime, start: datetime, end: datetime) -> bool:
    """Windows are half-open (start, end]: the triggering transfer at `end` counts."""
    return start < t <= end


def compute_account_stats(
    key: str,
    transfers: Sequence[TransferRecord],
    window_start: datetime,
    window_end: datetime,
    schema: FeatureSchema = PLATFORM_SCHEMA,
) -> AccountWindowStats:
    """Measure one account from ALL its transfers in the window.

    `transfers` must be every transfer touching `key` in the window across the
    source - not just those inside a scored subgraph. Transfers outside the
    window and self-transfers are ignored.
    """
    inbound: List[TransferRecord] = []
    outbound: List[TransferRecord] = []
    for t in transfers:
        if t.source == t.target or not in_window(t.occurred_at, window_start, window_end):
            continue
        if t.target == key:
            inbound.append(t)
        elif t.source == key:
            outbound.append(t)

    stats = AccountWindowStats(key=key, window_start=window_start, window_end=window_end)
    every = sorted(inbound + outbound, key=lambda t: (t.occurred_at, t.key))
    if not every:
        return stats

    stats.in_count = len(inbound)
    stats.out_count = len(outbound)
    stats.in_value = float(sum(t.amount for t in inbound))
    stats.out_value = float(sum(t.amount for t in outbound))
    stats.partners_in = len({t.source for t in inbound})
    stats.partners_out = len({t.target for t in outbound})

    high = max(stats.in_value, stats.out_value)
    stats.pass_through = min(stats.in_value, stats.out_value) / high if high > 0 else 0.0
    total = stats.in_value + stats.out_value
    stats.net_flow = (stats.in_value - stats.out_value) / total if total > 0 else 0.0

    # Relay: how soon each outbound transfer follows the latest earlier inbound
    stats.inbound_times = sorted(t.occurred_at for t in inbound)
    latencies: List[float] = []
    rapid_value = 0.0
    for t in outbound:
        prior = latest_before(stats.inbound_times, t.occurred_at)
        if prior is None:
            continue
        gap = t.occurred_at - prior
        latencies.append(gap.total_seconds() / 60.0)
        if gap <= RAPID_RELAY:
            rapid_value += t.amount
    stats.rapid_relay_share = rapid_value / stats.out_value if stats.out_value > 0 else 0.0
    stats.median_relay_minutes = statistics.median(latencies) if latencies else None

    amounts = [t.amount for t in every]
    mean = sum(amounts) / len(amounts)
    stats.amount_cv = (
        statistics.pstdev(amounts) / mean if len(amounts) >= 2 and mean > 0 else 0.0
    )
    stats.round_ratio = sum(1 for t in every if transfer_is_round(t)) / len(every)
    stats.near_threshold_ratio = sum(
        1 for t in every if transfer_near_threshold(t, schema)
    ) / len(every)
    if total > 0:
        stats.cross_border_share = sum(t.amount for t in every if t.is_international) / total
        stats.cross_institution_share = (
            sum(t.amount for t in every if t.cross_institution) / total
        )

    # Densest one-hour burst (two-pointer over the time-sorted transfers)
    best, left = 0, 0
    for right in range(len(every)):
        while every[right].occurred_at - every[left].occurred_at > _BURST_WINDOW:
            left += 1
        best = max(best, right - left + 1)
    stats.max_burst = best
    stats.timing_concentration = best / len(every)
    stats.active_days = len({t.occurred_at.date() for t in every})
    stats.last_activity_at = every[-1].occurred_at
    return stats


def latest_before(sorted_times: Sequence[datetime], t: datetime) -> Optional[datetime]:
    """Latest time strictly before `t` - funds must arrive before they can leave."""
    i = bisect.bisect_left(sorted_times, t)
    return sorted_times[i - 1] if i > 0 else None


# ---------------------------------------------------------------------------
# Feature vectors
# ---------------------------------------------------------------------------

_INDIVIDUAL = {"ACCOUNT", "CUSTOMER", "INDIVIDUAL"}
_WALLET_LIKE = {"WALLET", "BENEFICIARY"}
_RELAY_LOG_CAP = math.log1p(7 * 24 * 60)  # minutes in a default window


def _money(value: float) -> float:
    return float(min(math.log1p(max(value, 0.0)) / _MONEY_LOG_SCALE, 1.5))


def _capped_log(value: float, cap: float) -> float:
    return float(min(math.log1p(max(value, 0.0)) / cap, 1.0))


def _profile_vector(profile: AccountProfile) -> List[float]:
    entity = (profile.entity_type or "ACCOUNT").upper()
    return [
        1.0 if entity in _INDIVIDUAL else 0.0,
        1.0 if entity == "MERCHANT" else 0.0,
        1.0 if entity == "COMPANY" else 0.0,
        1.0 if entity in _WALLET_LIKE else 0.0,
        1.0 if profile.is_internal else 0.0,
        _capped_log(profile.account_age_days, _AGE_LOG_CAP),
        1.0 if profile.is_dormant else 0.0,
        1.0 if profile.high_risk_jurisdiction else 0.0,
        1.0 if profile.pep else 0.0,
    ]


def _behaviour_vector(stats: AccountWindowStats) -> List[float]:
    relay_speed = (
        1.0 / (1.0 + stats.median_relay_minutes / 60.0)
        if stats.median_relay_minutes is not None
        else 0.0
    )
    window_days = max((stats.window_end - stats.window_start).days, 1)
    return [
        _capped_log(stats.in_count, _COUNT_LOG_CAP),
        _capped_log(stats.out_count, _COUNT_LOG_CAP),
        _money(stats.in_value),
        _money(stats.out_value),
        _capped_log(stats.partners_in, _PARTNER_LOG_CAP),
        _capped_log(stats.partners_out, _PARTNER_LOG_CAP),
        stats.pass_through,
        stats.net_flow,
        stats.rapid_relay_share,
        relay_speed,
        min(stats.amount_cv, 3.0) / 3.0,
        stats.round_ratio,
        stats.near_threshold_ratio,
        stats.cross_border_share,
        stats.cross_institution_share,
        stats.timing_concentration,
        _capped_log(stats.max_burst, _BURST_LOG_CAP),
        min(stats.active_days / window_days, 1.0),
    ]


def account_feature_vector(
    profile: AccountProfile,
    stats: AccountWindowStats,
    schema: FeatureSchema = PLATFORM_SCHEMA,
) -> List[float]:
    """Account-level node features (all columns except the window-relative ones)."""
    profile_part = _profile_vector(profile) if schema.include_profile else []
    return profile_part + _behaviour_vector(stats)


def node_feature_vector(
    profile: AccountProfile,
    stats: AccountWindowStats,
    is_seed: bool,
    schema: FeatureSchema = PLATFORM_SCHEMA,
) -> List[float]:
    return account_feature_vector(profile, stats, schema) + [1.0 if is_seed else 0.0]


def edge_feature_vector(
    transfer: TransferRecord,
    sender: AccountWindowStats,
    receiver: AccountWindowStats,
    schema: FeatureSchema = PLATFORM_SCHEMA,
) -> List[float]:
    window = sender.window_end - sender.window_start
    prior = latest_before(sender.inbound_times, transfer.occurred_at)
    if prior is not None:
        minutes = (transfer.occurred_at - prior).total_seconds() / 60.0
        latency = _capped_log(minutes, _RELAY_LOG_CAP)
    else:
        latency = 1.0
    rail = payment_rail(transfer.channel)
    return [
        _money(transfer.amount),
        1.0 if transfer_is_round(transfer) else 0.0,
        1.0 if transfer_near_threshold(transfer, schema) else 0.0,
        1.0 if transfer.is_international else 0.0,
        1.0 if transfer.cross_institution else 0.0,
        transfer.amount / sender.out_value if sender.out_value > 0 else 0.0,
        transfer.amount / receiver.in_value if receiver.in_value > 0 else 0.0,
        1.0 if prior is not None else 0.0,
        latency,
        min(max((sender.window_end - transfer.occurred_at) / window, 0.0), 1.0),
        *[1.0 if rail == r else 0.0 for r in RAILS],
        1.0 if rail == "OTHER" else 0.0,
    ]


def as_matrix(rows: Sequence[Sequence[float]], width: int) -> np.ndarray:
    if not rows:
        return np.zeros((0, width), dtype=np.float32)
    return np.asarray(rows, dtype=np.float32)
