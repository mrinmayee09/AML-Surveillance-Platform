"""Behavioural feature extraction for the proactive AML layer.

Reads a customer's real transaction history out of the database and produces the
exact feature dictionary that `FEATURE_SPEC` defines, plus the human-readable
context an investigator needs to sanity-check each number.

This is the "Calculate customer behavioural features" step of the decision
pipeline. It runs server-side only; no feature is ever accepted from a client.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.graph.builder import HIGH_RISK_COUNTRIES
from app.ml.features import FeatureBundle
from app.models import Account, Counterparty, Customer, Transaction

# Windows used across the behavioural aggregates
RECENT_WINDOW_DAYS = 30
BASELINE_WINDOW_DAYS = 180
NEW_BENEFICIARY_WINDOW_DAYS = 30
BURST_WINDOW_MINUTES = 15
RAPID_MOVEMENT_WINDOW_MINUTES = 30
# Reporting threshold used for the structuring signal (demo configuration)
REPORTING_THRESHOLD = 1_000_000.0
STRUCTURING_BAND = (0.80, 0.999)  # fraction of the threshold counted as adjacent


@dataclass
class CustomerActivity:
    """A customer's transactions, split by direction and window."""

    outgoing: List[Transaction]
    incoming: List[Transaction]
    recent_outgoing: List[Transaction]
    recent_incoming: List[Transaction]
    account_ids: List[int]
    reference_time: datetime

    @property
    def all_transactions(self) -> List[Transaction]:
        return self.outgoing + self.incoming

    @property
    def recent_all(self) -> List[Transaction]:
        return self.recent_outgoing + self.recent_incoming


def load_activity(
    db: Session, customer: Customer, reference_time: Optional[datetime] = None
) -> CustomerActivity:
    """Fetch the transaction history behind a customer's behavioural profile."""
    now = reference_time or datetime.utcnow()
    account_ids = [a.id for a in customer.accounts]
    if not account_ids:
        return CustomerActivity([], [], [], [], [], now)

    horizon = now - timedelta(days=BASELINE_WINDOW_DAYS * 2)
    rows: Sequence[Transaction] = db.scalars(
        select(Transaction)
        .where(
            Transaction.occurred_at >= horizon,
            Transaction.occurred_at <= now,
            (Transaction.sender_account_id.in_(account_ids))
            | (Transaction.receiver_account_id.in_(account_ids)),
        )
        .order_by(Transaction.occurred_at)
    ).all()

    owned = set(account_ids)
    outgoing = [t for t in rows if t.sender_account_id in owned]
    incoming = [t for t in rows if t.receiver_account_id in owned]
    recent_cutoff = now - timedelta(days=RECENT_WINDOW_DAYS)

    return CustomerActivity(
        outgoing=outgoing,
        incoming=incoming,
        recent_outgoing=[t for t in outgoing if t.occurred_at >= recent_cutoff],
        recent_incoming=[t for t in incoming if t.occurred_at >= recent_cutoff],
        account_ids=account_ids,
        reference_time=now,
    )


# ---------------------------------------------------------------------------
# Individual signal computations
# ---------------------------------------------------------------------------


def _peak_per_hour(transactions: Sequence[Transaction]) -> int:
    """Largest number of transactions inside any rolling one-hour window."""
    if not transactions:
        return 0
    times = sorted(t.occurred_at for t in transactions)
    best = 1
    left = 0
    for right in range(len(times)):
        while times[right] - times[left] > timedelta(hours=1):
            left += 1
        best = max(best, right - left + 1)
    return best


def _burst_concentration(transactions: Sequence[Transaction]) -> float:
    """Share of activity inside the busiest fixed 15-minute slice."""
    if len(transactions) < 2:
        return 0.0
    times = sorted(t.occurred_at for t in transactions)
    base = times[0]
    buckets: Dict[int, int] = {}
    for ts in times:
        slot = int((ts - base).total_seconds() // (BURST_WINDOW_MINUTES * 60))
        buckets[slot] = buckets.get(slot, 0) + 1
    return max(buckets.values()) / len(times)


def _rapid_movement(activity: CustomerActivity) -> Tuple[float, List[Dict[str, object]]]:
    """Fraction of inbound value forwarded onward inside the rapid window.

    Returns the ratio plus the specific in/out pairs, so the reactive layer can
    quote a concrete example ("INR 10L received, INR 9.8L out 2 minutes later").
    """
    if not activity.recent_incoming or not activity.recent_outgoing:
        return 0.0, []

    window = timedelta(minutes=RAPID_MOVEMENT_WINDOW_MINUTES)
    outgoing = sorted(activity.recent_outgoing, key=lambda t: t.occurred_at)
    matched_value = 0.0
    total_inbound = sum(t.amount for t in activity.recent_incoming) or 1.0
    evidence: List[Dict[str, object]] = []
    consumed: set[int] = set()

    for inbound in sorted(activity.recent_incoming, key=lambda t: t.occurred_at):
        forwarded = 0.0
        followers: List[Transaction] = []
        for out in outgoing:
            if out.id in consumed:
                continue
            delay = out.occurred_at - inbound.occurred_at
            if timedelta(0) <= delay <= window:
                forwarded += out.amount
                followers.append(out)
                consumed.add(out.id)
                if forwarded >= inbound.amount * 0.9:
                    break
        if followers:
            captured = min(forwarded, inbound.amount)
            matched_value += captured
            gap_minutes = (followers[0].occurred_at - inbound.occurred_at).total_seconds() / 60
            evidence.append(
                {
                    "inbound_ref": inbound.txn_ref,
                    "inbound_amount": round(inbound.amount, 2),
                    "outbound_refs": [t.txn_ref for t in followers],
                    "outbound_amount": round(forwarded, 2),
                    "delay_minutes": round(gap_minutes, 1),
                    "forwarded_pct": round(min(forwarded / inbound.amount, 1.0) * 100, 1),
                }
            )

    evidence.sort(key=lambda e: e["outbound_amount"], reverse=True)  # type: ignore[arg-type]
    return min(matched_value / total_inbound, 1.0), evidence[:5]


def _structuring_score(transactions: Sequence[Transaction]) -> float:
    """Share of transactions sitting just below the reporting threshold."""
    if not transactions:
        return 0.0
    lo = REPORTING_THRESHOLD * STRUCTURING_BAND[0]
    hi = REPORTING_THRESHOLD * STRUCTURING_BAND[1]
    hits = sum(1 for t in transactions if lo <= t.amount <= hi)
    return hits / len(transactions)


def _round_amount_ratio(transactions: Sequence[Transaction]) -> float:
    if not transactions:
        return 0.0
    hits = 0
    for txn in transactions:
        for unit in (100_000, 10_000, 1_000):
            if txn.amount >= unit and abs(txn.amount % unit) < 1e-6:
                hits += 1
                break
    return hits / len(transactions)


def _counterparty_counts(
    db: Session, customer: Customer, activity: CustomerActivity
) -> Tuple[int, int, int]:
    """(unique in recent window, new in window, historical baseline)."""
    owned = set(activity.account_ids)
    recent_partners: set[int] = set()
    for txn in activity.recent_all:
        partner = (
            txn.receiver_account_id
            if txn.sender_account_id in owned
            else txn.sender_account_id
        )
        if partner not in owned:
            recent_partners.add(partner)

    cutoff = activity.reference_time - timedelta(days=NEW_BENEFICIARY_WINDOW_DAYS)
    new_partners = int(
        db.scalar(
            select(func.count(Counterparty.id)).where(
                Counterparty.customer_id == customer.id,
                Counterparty.first_seen_at >= cutoff,
            )
        )
        or 0
    )

    baseline = customer.baseline_counterparties or 0
    if baseline == 0:
        # Derive a baseline from history outside the recent window
        historical: set[int] = set()
        recent_cutoff = activity.reference_time - timedelta(days=RECENT_WINDOW_DAYS)
        for txn in activity.all_transactions:
            if txn.occurred_at >= recent_cutoff:
                continue
            partner = (
                txn.receiver_account_id
                if txn.sender_account_id in owned
                else txn.sender_account_id
            )
            if partner not in owned:
                historical.add(partner)
        baseline = len(historical)

    return len(recent_partners), new_partners, baseline


def _geo_exposure(transactions: Sequence[Transaction]) -> Tuple[float, float]:
    """(international share, elevated-risk jurisdiction share by value)."""
    if not transactions:
        return 0.0, 0.0
    intl = sum(1 for t in transactions if t.is_international)
    total_value = sum(t.amount for t in transactions) or 1.0
    risky_value = sum(t.amount for t in transactions if t.country in HIGH_RISK_COUNTRIES)
    return intl / len(transactions), min(risky_value / total_value, 1.0)


def _dormancy_reactivation(
    customer: Customer, activity: CustomerActivity, avg_recent: float
) -> float:
    """1.0 when a quiet relationship suddenly resumed material activity."""
    if not activity.recent_all:
        return 0.0
    recent_cutoff = activity.reference_time - timedelta(days=RECENT_WINDOW_DAYS)
    prior = [t for t in activity.all_transactions if t.occurred_at < recent_cutoff]
    if len(prior) > 5:
        return 0.0
    dormant_account = any(a.is_dormant for a in customer.accounts)
    material = avg_recent >= 100_000
    return 1.0 if (material and (len(prior) <= 5 or dormant_account)) else 0.0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract_features(
    db: Session,
    customer: Customer,
    prospective_amount: Optional[float] = None,
    prospective_country: Optional[str] = None,
    reference_time: Optional[datetime] = None,
) -> FeatureBundle:
    """Build the proactive feature vector for a customer.

    `prospective_amount` lets the pre-transaction gateway score a payment that
    has not happened yet: the pending amount is folded into the amount-deviation
    and velocity signals without being written to the database.
    """
    activity = load_activity(db, customer, reference_time)
    recent = activity.recent_all
    history = activity.all_transactions

    amounts_recent = [t.amount for t in recent]
    amounts_history = [t.amount for t in history]

    baseline_avg = customer.baseline_avg_amount or (
        statistics.fmean(amounts_history) if amounts_history else 0.0
    )
    if baseline_avg <= 0:
        baseline_avg = statistics.fmean(amounts_recent) if amounts_recent else 1.0

    # The amount under assessment: the pending payment if given, else the
    # customer's recent average.
    subject_amount = (
        float(prospective_amount)
        if prospective_amount is not None
        else (statistics.fmean(amounts_recent) if amounts_recent else baseline_avg)
    )
    amount_deviation = subject_amount / baseline_avg if baseline_avg > 0 else 1.0

    # Frequency: recent monthly rate against the established baseline
    recent_count = len(recent)
    baseline_monthly = customer.baseline_monthly_count or 0.0
    if baseline_monthly <= 0:
        span_days = max(
            (activity.reference_time - min((t.occurred_at for t in history), default=activity.reference_time)).days,
            1,
        )
        baseline_monthly = len(history) / max(span_days / 30.0, 1.0)
    frequency_ratio = recent_count / baseline_monthly if baseline_monthly > 0 else 1.0

    peak_hour = _peak_per_hour(recent)
    if prospective_amount is not None:
        # A pending payment adds one to the current hour's count
        peak_hour += 1
    burst = _burst_concentration(recent)
    rapid_score, rapid_evidence = _rapid_movement(activity)

    unique_cp, new_cp, baseline_cp = _counterparty_counts(db, customer, activity)
    cp_growth = unique_cp / baseline_cp if baseline_cp > 0 else (1.0 if unique_cp <= 1 else float(unique_cp))

    intl_share, geo_risk = _geo_exposure(recent)
    if prospective_country and prospective_country in HIGH_RISK_COUNTRIES:
        geo_risk = max(geo_risk, 0.35)
    geo_risk = max(geo_risk, customer.risk_country_exposure or 0.0)

    avg_recent = statistics.fmean(amounts_recent) if amounts_recent else 0.0
    dormancy = _dormancy_reactivation(customer, activity, avg_recent)

    values: Dict[str, float] = {
        "amount_deviation_ratio": amount_deviation,
        "amount_log": math.log1p(max(subject_amount, 0.0)),
        "txn_count_30d": float(recent_count),
        "frequency_ratio": frequency_ratio,
        "velocity_per_hour": float(peak_hour),
        "burst_score": burst,
        "unique_counterparties_30d": float(unique_cp),
        "new_counterparties_30d": float(new_cp),
        "counterparty_growth_ratio": cp_growth,
        "rapid_movement_score": rapid_score,
        "structuring_score": _structuring_score(recent),
        "round_amount_ratio": _round_amount_ratio(recent),
        "international_share": intl_share,
        "high_risk_geo_exposure": geo_risk,
        "account_age_years": float(customer.account_age_years or 0.0),
        "previous_alert_count": float(customer.previous_alert_count or 0),
        "dormancy_reactivation": dormancy,
        "pep_flag": 1.0 if customer.pep_flag else 0.0,
    }

    # Extra metrics: not model inputs, but consumed by rules and the UI
    context: Dict[str, object] = {
        "amount": subject_amount,
        "baseline_avg_amount": baseline_avg,
        "baseline_monthly_count": baseline_monthly,
        "baseline_counterparties": float(baseline_cp),
        "avg_recent_amount": avg_recent,
        "median_recent_amount": (
            statistics.median(amounts_recent) if amounts_recent else 0.0
        ),
        "max_recent_amount": max(amounts_recent) if amounts_recent else 0.0,
        "total_transactions": float(len(history)),
        "total_outflow": float(sum(t.amount for t in activity.outgoing)),
        "total_inflow": float(sum(t.amount for t in activity.incoming)),
        "recent_outgoing_count": float(len(activity.recent_outgoing)),
        "recent_incoming_count": float(len(activity.recent_incoming)),
        "rapid_movement_evidence": rapid_evidence,
        # Composite drift index consumed by BEHAVIOURAL_DEVIATION
        "behaviour_drift": round(
            (amount_deviation * 0.4) + (frequency_ratio * 0.35) + (cp_growth * 0.25), 3
        ),
        "velocity_label": (
            "HIGH" if peak_hour >= 8 else "MEDIUM" if peak_hour >= 4 else "LOW"
        ),
    }

    return FeatureBundle(values=values, context=context)


def rule_metrics(bundle: FeatureBundle) -> Dict[str, float]:
    """Flatten features + numeric context into the rules engine's input dict."""
    metrics: Dict[str, float] = dict(bundle.as_dict())
    for key, value in bundle.context.items():
        if isinstance(value, (int, float)):
            metrics[key] = float(value)
    return metrics
