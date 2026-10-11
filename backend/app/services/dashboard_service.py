"""Dashboard aggregations.

All figures are computed from the database with SQL aggregates - nothing on the
dashboard is a hard-coded display value. Deltas compare the selected window
against the immediately preceding window of equal length.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import Float, case, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.types import utcnow
from app.models import Alert, Customer, Investigation, Network, Transaction
from app.models.enums import AlertStatus
from app.services import alert_service, investigation_service, network_service

WINDOWS: Dict[str, timedelta] = {
    "24H": timedelta(hours=24),
    "7D": timedelta(days=7),
    "30D": timedelta(days=30),
    "90D": timedelta(days=90),
}

# Bucket granularity per window, so a chart never renders 2,000 points.
# Two format dialects are needed because SQLite uses strftime() while
# PostgreSQL uses to_char() with different placeholders.
BUCKET_FORMAT: Dict[str, str] = {
    "24H": "%Y-%m-%d %H:00",
    "7D": "%Y-%m-%d",
    "30D": "%Y-%m-%d",
    "90D": "%Y-W%W",
}
BUCKET_FORMAT_PG: Dict[str, str] = {
    "24H": "YYYY-MM-DD HH24:00",
    "7D": "YYYY-MM-DD",
    "30D": "YYYY-MM-DD",
    "90D": "YYYY-\"W\"IW",
}


def _bucket_expr(db: Session, column, window: str):
    """Dialect-aware timestamp truncation, so the same code runs on both engines."""
    dialect = db.get_bind().dialect.name
    key = window.upper()
    if dialect == "sqlite":
        return func.strftime(BUCKET_FORMAT.get(key, "%Y-%m-%d"), column)
    return func.to_char(column, BUCKET_FORMAT_PG.get(key, "YYYY-MM-DD"))

DASHBOARD_ADVISORY = (
    "Figures describe model- and rule-generated risk indicators across monitored "
    "activity. Elevated counts indicate review workload, not confirmed misconduct."
)

REGION_BY_CITY: Dict[str, str] = {
    "Mumbai": "West",
    "Pune": "West",
    "Ahmedabad": "West",
    "Delhi": "North",
    "Gurugram": "North",
    "Noida": "North",
    "Jaipur": "North",
    "Bengaluru": "South",
    "Chennai": "South",
    "Hyderabad": "South",
    "Kochi": "South",
    "Kolkata": "East",
    "Bhubaneswar": "East",
    "Guwahati": "North East",
}


def _window_bounds(window: str, now: Optional[datetime] = None) -> Tuple[datetime, datetime, timedelta]:
    reference = now or utcnow()
    span = WINDOWS.get(window.upper(), WINDOWS["7D"])
    return reference - span, reference, span


def _delta(current: float, previous: float) -> Tuple[Optional[float], str]:
    if previous <= 0:
        return (None, "flat") if current == 0 else (None, "up")
    change = (current - previous) / previous * 100.0
    direction = "up" if change > 0.5 else "down" if change < -0.5 else "flat"
    return round(change, 1), direction


def _count_transactions(db: Session, start: datetime, end: datetime) -> int:
    return int(
        db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.occurred_at >= start, Transaction.occurred_at < end
            )
        )
        or 0
    )


def _count_high_risk(db: Session, start: datetime, end: datetime) -> int:
    return int(
        db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.occurred_at >= start,
                Transaction.occurred_at < end,
                Transaction.risk_level.in_(["HIGH", "CRITICAL"]),
            )
        )
        or 0
    )


def _count_alerts(db: Session, start: datetime, end: datetime) -> int:
    return int(
        db.scalar(
            select(func.count(Alert.id)).where(
                Alert.raised_at >= start, Alert.raised_at < end
            )
        )
        or 0
    )


def _volume(db: Session, start: datetime, end: datetime) -> float:
    return float(
        db.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0.0)).where(
                Transaction.occurred_at >= start, Transaction.occurred_at < end
            )
        )
        or 0.0
    )


def _fmt_count(value: float) -> str:
    return f"{int(value):,}"


def _fmt_money(value: float) -> str:
    if value >= 1_00_00_000:
        return f"INR {value / 1_00_00_000:,.2f} Cr"
    if value >= 1_00_000:
        return f"INR {value / 1_00_000:,.2f} L"
    return f"INR {value:,.0f}"


def build_kpis(db: Session, window: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    start, end, span = _window_bounds(window, now)
    prev_start = start - span

    total = _count_transactions(db, start, end)
    prev_total = _count_transactions(db, prev_start, start)
    high = _count_high_risk(db, start, end)
    prev_high = _count_high_risk(db, prev_start, start)
    alerts = _count_alerts(db, start, end)
    prev_alerts = _count_alerts(db, prev_start, start)
    volume = _volume(db, start, end)
    prev_volume = _volume(db, prev_start, start)

    monitored = int(
        db.scalar(
            select(func.count(Customer.id)).where(Customer.under_monitoring.is_(True))
        )
        or 0
    )
    open_alerts = alert_service.open_alert_count(db)
    active_cases = investigation_service.active_count(db)
    networks = network_service.suspicious_count(db)

    total_delta, total_dir = _delta(total, prev_total)
    high_delta, high_dir = _delta(high, prev_high)
    alert_delta, alert_dir = _delta(alerts, prev_alerts)
    volume_delta, volume_dir = _delta(volume, prev_volume)

    return [
        {
            "key": "transactions",
            "label": "Transactions monitored",
            "value": float(total),
            "display": _fmt_count(total),
            "delta_pct": total_delta,
            "direction": total_dir,
            "sentiment": "neutral",
            "hint": f"Settled in the last {window.upper()}, all screened by the AML pipeline.",
        },
        {
            "key": "volume",
            "label": "Transaction volume",
            "value": volume,
            "display": _fmt_money(volume),
            "delta_pct": volume_delta,
            "direction": volume_dir,
            "sentiment": "neutral",
            "hint": "Total value screened in the selected window.",
        },
        {
            "key": "high_risk",
            "label": "High-risk transactions",
            "value": float(high),
            "display": _fmt_count(high),
            "delta_pct": high_delta,
            "direction": high_dir,
            "sentiment": "bad" if high_dir == "up" else "good",
            "hint": "Scored HIGH or CRITICAL. Requires review, not proof of misconduct.",
        },
        {
            "key": "active_alerts",
            "label": "Active alerts",
            "value": float(open_alerts),
            "display": _fmt_count(open_alerts),
            "delta_pct": alert_delta,
            "direction": alert_dir,
            "sentiment": "bad" if alert_dir == "up" else "good",
            "hint": "New, under review or escalated across all detection layers.",
        },
        {
            "key": "monitored_customers",
            "label": "Customers under monitoring",
            "value": float(monitored),
            "display": _fmt_count(monitored),
            "delta_pct": None,
            "direction": "flat",
            "sentiment": "neutral",
            "hint": "Placed under enhanced monitoring by the proactive layer.",
        },
        {
            "key": "investigations",
            "label": "Active investigations",
            "value": float(active_cases),
            "display": _fmt_count(active_cases),
            "delta_pct": None,
            "direction": "flat",
            "sentiment": "neutral",
            "hint": "Open case files assigned to analysts.",
        },
        {
            "key": "networks",
            "label": "Suspicious networks",
            "value": float(networks),
            "display": _fmt_count(networks),
            "delta_pct": None,
            "direction": "flat",
            "sentiment": "bad" if networks > 0 else "good",
            "hint": "Clusters flagged by the graph + GNN layer for investigation.",
        },
    ]


def risk_distribution(db: Session, window: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    start, end, _ = _window_bounds(window, now)
    rows = db.execute(
        select(Transaction.risk_level, func.count(Transaction.id))
        .where(Transaction.occurred_at >= start, Transaction.occurred_at < end)
        .group_by(Transaction.risk_level)
    ).all()
    counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    for level, count in rows:
        if level in counts:
            counts[level] = int(count)

    total = sum(counts.values()) or 1
    meta = {
        "LOW": ("Low", "Allow", "green"),
        "MEDIUM": ("Medium", "Monitor / additional verification", "amber"),
        "HIGH": ("High", "Review / hold", "red"),
        "CRITICAL": ("Critical", "Block / escalate", "red"),
    }
    return [
        {
            "key": level,
            "label": meta[level][0],
            "count": count,
            "share": round(count / total * 100, 1),
            "action": meta[level][1],
            "tone": meta[level][2],
        }
        for level, count in counts.items()
    ]


def time_series(db: Session, window: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Per-bucket transaction, risk-band, alert and volume series."""
    start, end, span = _window_bounds(window, now)

    txn_rows = db.execute(
        select(
            _bucket_expr(db, Transaction.occurred_at, window).label("bucket"),
            func.count(Transaction.id),
            func.sum(case((Transaction.risk_level == "LOW", 1), else_=0)),
            func.sum(case((Transaction.risk_level == "MEDIUM", 1), else_=0)),
            func.sum(case((Transaction.risk_level == "HIGH", 1), else_=0)),
            func.sum(case((Transaction.risk_level == "CRITICAL", 1), else_=0)),
            func.coalesce(func.sum(Transaction.amount), 0.0),
            func.coalesce(func.avg(Transaction.risk_score), 0.0),
        )
        .where(Transaction.occurred_at >= start, Transaction.occurred_at < end)
        .group_by("bucket")
        .order_by("bucket")
    ).all()

    alert_rows = db.execute(
        select(
            _bucket_expr(db, Alert.raised_at, window).label("bucket"),
            func.count(Alert.id),
        )
        .where(Alert.raised_at >= start, Alert.raised_at < end)
        .group_by("bucket")
    ).all()
    alerts_by_bucket = {bucket: int(count) for bucket, count in alert_rows}

    series: List[Dict[str, Any]] = []
    for bucket, total, low, medium, high, critical, volume, avg_risk in txn_rows:
        total_i = int(total or 0)
        suspicious = int(high or 0) + int(critical or 0)
        series.append(
            {
                "bucket": bucket,
                "label": _bucket_label(bucket, window),
                "total": float(total_i),
                "low": float(low or 0),
                "medium": float(medium or 0),
                "high": float(high or 0),
                "critical": float(critical or 0),
                "alerts": float(alerts_by_bucket.get(bucket, 0)),
                "volume": round(float(volume or 0.0), 2),
                "suspicious_pct": round(suspicious / total_i * 100, 2) if total_i else 0.0,
                "avg_risk": round(float(avg_risk or 0.0), 2),
            }
        )
    return series


def _bucket_label(bucket: str, window: str) -> str:
    try:
        if window.upper() == "24H":
            return datetime.strptime(bucket, "%Y-%m-%d %H:00").strftime("%H:00")
        if window.upper() in {"7D", "30D"}:
            return datetime.strptime(bucket, "%Y-%m-%d").strftime("%d %b")
    except (ValueError, TypeError):
        pass
    return bucket


def geo_risk(db: Session, window: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    start, end, _ = _window_bounds(window, now)
    rows = db.execute(
        select(
            Transaction.city,
            Transaction.country,
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.amount), 0.0),
            func.sum(
                case((Transaction.risk_level.in_(["HIGH", "CRITICAL"]), 1), else_=0)
            ),
            func.coalesce(func.avg(Transaction.risk_score), 0.0),
        )
        .where(Transaction.occurred_at >= start, Transaction.occurred_at < end)
        .group_by(Transaction.city, Transaction.country)
        .order_by(func.count(Transaction.id).desc())
        .limit(14)
    ).all()

    output: List[Dict[str, Any]] = []
    for city, country, count, volume, high, avg_risk in rows:
        avg = round(float(avg_risk or 0.0), 1)
        output.append(
            {
                "region": REGION_BY_CITY.get(city, city or "Unknown"),
                "country": f"{city}, {country}" if city else country,
                "transactions": int(count or 0),
                "volume": round(float(volume or 0.0), 2),
                "high_risk_count": int(high or 0),
                "avg_risk": avg,
                "risk_level": settings.risk_level_for(avg),
            }
        )
    return output


def channel_breakdown(db: Session, window: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    start, end, _ = _window_bounds(window, now)
    rows = db.execute(
        select(
            Transaction.channel,
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.amount), 0.0),
            func.coalesce(func.avg(Transaction.risk_score), 0.0),
            func.sum(case((Transaction.risk_level.in_(["HIGH", "CRITICAL"]), 1), else_=0)),
        )
        .where(Transaction.occurred_at >= start, Transaction.occurred_at < end)
        .group_by(Transaction.channel)
        .order_by(func.count(Transaction.id).desc())
    ).all()
    return [
        {
            "channel": channel,
            "count": int(count or 0),
            "volume": round(float(volume or 0.0), 2),
            "avg_risk": round(float(avg_risk or 0.0), 1),
            "high_risk_count": int(high or 0),
        }
        for channel, count, volume, avg_risk, high in rows
    ]


def top_alerts(db: Session, limit: int = 6) -> List[Dict[str, Any]]:
    rows = db.scalars(
        select(Alert)
        .where(
            Alert.status.in_(
                [AlertStatus.NEW.value, AlertStatus.UNDER_REVIEW.value, AlertStatus.ESCALATED.value]
            )
        )
        .order_by(Alert.risk_score.desc(), Alert.raised_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "alert_ref": a.alert_ref,
            "title": a.title,
            "source": a.source,
            "alert_type": a.alert_type,
            "risk_score": a.risk_score,
            "risk_level": a.risk_level,
            "status": a.status,
            "raised_at": a.raised_at.isoformat(),
            "customer_ref": a.customer.customer_ref if a.customer else None,
            "customer_name": a.customer.name if a.customer else None,
        }
        for a in rows
    ]


def pipeline_health(db: Session, window: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Throughput of each surveillance layer - the narrative spine of the product."""
    start, end, _ = _window_bounds(window, now)
    from app.gnn.registry import get_gnn_engine
    from app.ml.registry import get_proactive_model

    screened = _count_transactions(db, start, end)
    integrity_failures = int(
        db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.occurred_at >= start,
                Transaction.occurred_at < end,
                Transaction.integrity_status != "VERIFIED",
            )
        )
        or 0
    )
    blocked = int(
        db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.occurred_at >= start,
                Transaction.occurred_at < end,
                Transaction.decision.in_(["BLOCK", "REVIEW"]),
            )
        )
        or 0
    )
    proactive_alerts = int(
        db.scalar(
            select(func.count(Alert.id)).where(
                Alert.raised_at >= start, Alert.raised_at < end, Alert.source == "PROACTIVE"
            )
        )
        or 0
    )
    reactive_alerts = int(
        db.scalar(
            select(func.count(Alert.id)).where(
                Alert.raised_at >= start, Alert.raised_at < end, Alert.source == "REACTIVE"
            )
        )
        or 0
    )
    network_alerts = int(
        db.scalar(
            select(func.count(Alert.id)).where(
                Alert.raised_at >= start, Alert.raised_at < end, Alert.source == "NETWORK"
            )
        )
        or 0
    )

    model = get_proactive_model()
    engine = get_gnn_engine()

    return [
        {
            "stage": "Transaction integrity",
            "layer": "INTEGRITY",
            "throughput": screened,
            "flagged": integrity_failures,
            "engine": "Deterministic server-side validation",
            "trained": None,
            "detail": "Compares each payment request against orders.authorized_amount.",
        },
        {
            "stage": "Proactive AML",
            "layer": "PROACTIVE",
            "throughput": screened,
            "flagged": blocked,
            "engine": model.model_type,
            "trained": model.trained,
            "detail": f"{proactive_alerts} pre-transaction alert(s) raised in this window.",
        },
        {
            "stage": "Reactive monitoring",
            "layer": "REACTIVE",
            "throughput": screened,
            "flagged": reactive_alerts,
            "engine": "Rule + behavioural pattern detectors",
            "trained": None,
            "detail": "Post-settlement sweep across five laundering typologies.",
        },
        {
            "stage": "Graph + GNN",
            "layer": "NETWORK",
            "throughput": int(
                db.scalar(select(func.count(Network.id)).where(Network.is_active.is_(True)))
                or 0
            ),
            "flagged": network_service.suspicious_count(db),
            "engine": engine.architecture,
            "trained": engine.trained,
            "detail": f"{network_alerts} network alert(s) raised in this window.",
        },
    ]


def build_overview(db: Session, window: str = "7D", now: Optional[datetime] = None) -> Dict[str, Any]:
    normalised = window.upper() if window.upper() in WINDOWS else "7D"
    return {
        "window": normalised,
        "generated_at": now or utcnow(),
        "kpis": build_kpis(db, normalised, now),
        "risk_distribution": risk_distribution(db, normalised, now),
        "series": time_series(db, normalised, now),
        "geo_risk": geo_risk(db, normalised, now),
        "channel_breakdown": channel_breakdown(db, normalised, now),
        "top_alerts": top_alerts(db),
        "suspicious_networks": network_service.suspicious_summary(db),
        "pipeline_health": pipeline_health(db, normalised, now),
        "advisory": DASHBOARD_ADVISORY,
    }
