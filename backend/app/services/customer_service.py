"""Customer profile, behavioural statistics and risk trajectory."""

from __future__ import annotations

import statistics
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.types import utcnow
from app.models import Counterparty, Customer, RiskAssessment, Transaction
from app.models.enums import AssessmentKind
from app.rules.engine import evaluate, load_behavioural_rules
from app.services import feature_service, risk_service


def behavioural_stats(db: Session, customer: Customer) -> Dict[str, Any]:
    """The behavioural aggregates shown on the customer profile page."""
    activity = feature_service.load_activity(db, customer)
    recent = activity.recent_all
    history = activity.all_transactions

    amounts_recent = [t.amount for t in recent]
    amounts_all = [t.amount for t in history]

    span_days = 1
    if history:
        earliest = min(t.occurred_at for t in history)
        span_days = max((utcnow() - earliest).days, 1)

    new_cp = int(
        db.scalar(
            select(func.count(Counterparty.id)).where(
                Counterparty.customer_id == customer.id,
                Counterparty.first_seen_at >= utcnow() - timedelta(days=30),
            )
        )
        or 0
    )
    unique_cp = int(
        db.scalar(
            select(func.count(Counterparty.id)).where(
                Counterparty.customer_id == customer.id
            )
        )
        or 0
    )

    peak = feature_service._peak_per_hour(recent)  # noqa: SLF001
    intl = sum(1 for t in recent if t.is_international)
    baseline = customer.baseline_avg_amount or (
        statistics.fmean(amounts_all) if amounts_all else 0.0
    )
    avg_recent = statistics.fmean(amounts_recent) if amounts_recent else 0.0

    return {
        "avg_transaction_amount": round(avg_recent, 2),
        "median_transaction_amount": round(
            statistics.median(amounts_recent) if amounts_recent else 0.0, 2
        ),
        "max_transaction_amount": round(max(amounts_recent) if amounts_recent else 0.0, 2),
        "transactions_per_month": round(len(history) / max(span_days / 30.0, 1.0), 1),
        "total_transactions": len(history),
        "unique_counterparties": unique_cp,
        "new_counterparties_30d": new_cp,
        "international_share": round(intl / len(recent) * 100, 1) if recent else 0.0,
        "velocity_label": "HIGH" if peak >= 8 else "MEDIUM" if peak >= 4 else "LOW",
        "velocity_max_per_hour": peak,
        "previous_alerts": customer.previous_alert_count or 0,
        "total_outflow": round(sum(t.amount for t in activity.outgoing), 2),
        "total_inflow": round(sum(t.amount for t in activity.incoming), 2),
        "baseline_avg_amount": round(baseline, 2),
        "amount_deviation_ratio": round(avg_recent / baseline, 2) if baseline > 0 else 1.0,
    }


def risk_trajectory(
    db: Session, customer: Customer, weeks: int = 8
) -> List[Dict[str, Any]]:
    """Weekly risk history: the trajectory chart on the proactive page."""
    cutoff = utcnow() - timedelta(weeks=weeks)
    rows: Sequence[RiskAssessment] = db.scalars(
        select(RiskAssessment)
        .where(
            RiskAssessment.customer_id == customer.id,
            RiskAssessment.assessed_at >= cutoff,
        )
        .order_by(RiskAssessment.assessed_at)
    ).all()

    if not rows:
        return []

    # Bucket into calendar weeks relative to the earliest assessment
    origin = rows[0].assessed_at
    buckets: Dict[int, List[RiskAssessment]] = {}
    for row in rows:
        index = max(int((row.assessed_at - origin).days // 7), 0)
        buckets.setdefault(index, []).append(row)

    trajectory: List[Dict[str, Any]] = []
    for index in sorted(buckets):
        group = buckets[index]
        score = round(sum(a.risk_score for a in group) / len(group), 1)
        trajectory.append(
            {
                "label": f"Week {index + 1}",
                "period_start": min(a.assessed_at for a in group),
                "risk_score": score,
                "risk_level": settings.risk_level_for(score),
            }
        )
    return trajectory


def risk_profile(db: Session, customer: Customer) -> Dict[str, Any]:
    """Recompute the customer's proactive risk with a full explanation."""
    bundle = feature_service.extract_features(db, customer)
    metrics = feature_service.rule_metrics(bundle)
    hits = evaluate(load_behavioural_rules(db), metrics)
    trend = risk_service.determine_trend(db, customer, customer.current_risk_score or 0.0)
    result = risk_service.score(bundle, hits, trend=trend)

    return {
        "customer_ref": customer.customer_ref,
        "name": customer.name,
        "risk_score": result.score,
        "risk_level": result.level,
        "trend": result.trend,
        "decision": result.decision,
        "assessed_at": utcnow(),
        "model_probability": result.model_probability,
        "provenance": result.provenance,
        "factors": result.factors,
        "features": result.features,
        "trajectory": risk_trajectory(db, customer),
        "behaviour": behavioural_stats(db, customer),
        "triggered_rules": result.triggered_rule_codes,
        "advisory": risk_service.RISK_ADVISORY,
    }


def to_list_item(customer: Customer) -> Dict[str, Any]:
    return {
        "id": customer.id,
        "customer_ref": customer.customer_ref,
        "name": customer.name,
        "city": customer.city,
        "country": customer.country,
        "account_age_years": customer.account_age_years,
        "kyc_level": customer.kyc_level,
        "pep_flag": customer.pep_flag,
        "current_risk_score": customer.current_risk_score,
        "current_risk_level": customer.current_risk_level,
        "risk_trend": customer.risk_trend,
        "under_monitoring": customer.under_monitoring,
        "previous_alert_count": customer.previous_alert_count,
    }


def proactive_overview(db: Session, limit: int = 25) -> Dict[str, Any]:
    """Portfolio-level view for the Proactive Risk Intelligence page."""
    customers: Sequence[Customer] = db.scalars(
        select(Customer).order_by(Customer.current_risk_score.desc())
    ).all()

    monitored = [c for c in customers if c.under_monitoring]
    escalating = [c for c in customers if c.risk_trend == "INCREASING"]
    scores = [c.current_risk_score for c in customers if c.current_risk_score]

    watchlist: List[Dict[str, Any]] = []
    for customer in customers[:limit]:
        history: Sequence[RiskAssessment] = db.scalars(
            select(RiskAssessment)
            .where(
                RiskAssessment.customer_id == customer.id,
                RiskAssessment.kind == AssessmentKind.PROACTIVE.value,
            )
            .order_by(RiskAssessment.assessed_at.desc())
            .limit(8)
        ).all()

        delta = 0.0
        if len(history) >= 2:
            delta = round(history[0].risk_score - history[-1].risk_score, 1)

        top_factor = "No dominant factor recorded"
        if history and history[0].factors:
            top_factor = history[0].factors[0].get("label", top_factor)

        watchlist.append(
            {
                "customer_ref": customer.customer_ref,
                "name": customer.name,
                "risk_score": customer.current_risk_score,
                "risk_level": customer.current_risk_level,
                "trend": customer.risk_trend,
                "delta_30d": delta,
                "top_factor": top_factor,
                "monitored": customer.under_monitoring,
            }
        )

    # Portfolio-average risk over the last 12 weeks
    cutoff = utcnow() - timedelta(weeks=12)
    rows = db.scalars(
        select(RiskAssessment)
        .where(
            RiskAssessment.kind == AssessmentKind.PROACTIVE.value,
            RiskAssessment.assessed_at >= cutoff,
        )
        .order_by(RiskAssessment.assessed_at)
    ).all()

    weekly: Dict[int, List[float]] = {}
    if rows:
        origin = rows[0].assessed_at
        for row in rows:
            index = max(int((row.assessed_at - origin).days // 7), 0)
            weekly.setdefault(index, []).append(row.risk_score)

    trend_series = [
        {
            "label": f"Week {index + 1}",
            "value": round(sum(values) / len(values), 1),
        }
        for index, values in sorted(weekly.items())
    ]

    return {
        "total_monitored": len(monitored),
        "escalating_count": len(escalating),
        "avg_risk_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "band_counts": risk_service.risk_band_counts(scores),
        "watchlist": watchlist,
        "portfolio_trend": trend_series,
        "advisory": (
            "The proactive layer monitors behavioural drift BEFORE transactions are "
            "authorised. An increasing trajectory indicates emerging risk that warrants "
            "enhanced due diligence, not a conclusion about the customer."
        ),
    }
