"""Reactive AML monitoring.

Runs AFTER transactions have settled and asks a different question from the
proactive layer: not "should we allow this?" but "looking back, does this
activity form a suspicious pattern?"

Five detectors, each producing a narrative alert with the concrete numbers behind
it:

  * UNUSUAL_AMOUNT        - a transaction far outside the customer's own norm
  * HIGH_VELOCITY         - many transactions inside a short window
  * RAPID_FUND_MOVEMENT   - value received and forwarded almost immediately
  * MULTIPLE_COUNTERPARTIES - a burst of new beneficiaries
  * BEHAVIOURAL_ANOMALY   - sustained drift from the established baseline

Detectors read their thresholds from the rules engine, so an admin retuning a
rule changes what the reactive layer flags.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Alert, Customer, Transaction
from app.models.enums import AlertSource, AssessmentKind
from app.rules.engine import RuleHit, evaluate, load_rules
from app.services import alert_service, feature_service, risk_service
from app.services.feature_service import CustomerActivity

REACTIVE_ADVISORY = (
    "Reactive monitoring reviews settled transactions for potential laundering "
    "patterns. Findings are model- and rule-generated risk indicators requiring "
    "human investigation; they are not determinations of criminal conduct."
)

# How far back a monitoring sweep looks
DEFAULT_WINDOW_DAYS = 30


def _fmt_inr(value: float) -> str:
    """Indian-numbering short form: lakh / crore, as an analyst would read it."""
    if value >= 1_00_00_000:
        return f"INR {value / 1_00_00_000:.2f} Cr"
    if value >= 1_00_000:
        return f"INR {value / 1_00_000:.2f} L"
    if value >= 1_000:
        return f"INR {value / 1_000:.1f} K"
    return f"INR {value:,.0f}"


class Detection:
    """One reactive finding, ready to become an alert."""

    def __init__(
        self,
        code: str,
        name: str,
        headline: str,
        explanation: str,
        severity_score: float,
        metrics: List[Dict[str, Any]],
        transaction_refs: List[str],
        rule_code: Optional[str] = None,
        transaction_id: Optional[int] = None,
    ):
        self.code = code
        self.name = name
        self.headline = headline
        self.explanation = explanation
        self.severity_score = severity_score
        self.metrics = metrics
        self.transaction_refs = transaction_refs
        self.rule_code = rule_code
        self.transaction_id = transaction_id


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def detect_unusual_amount(
    customer: Customer, activity: CustomerActivity, threshold_ratio: float
) -> Optional[Detection]:
    if not activity.recent_all:
        return None
    baseline = customer.baseline_avg_amount or 0.0
    if baseline <= 0:
        return None

    largest = max(activity.recent_all, key=lambda t: t.amount)
    ratio = largest.amount / baseline
    if ratio < threshold_ratio:
        return None

    return Detection(
        code="UNUSUAL_AMOUNT",
        name="Unusual transaction amount",
        headline=(
            f"Customer normally transacts around {_fmt_inr(baseline)}. "
            f"Observed: {_fmt_inr(largest.amount)}."
        ),
        explanation=(
            f"Transaction {largest.txn_ref} moved {_fmt_inr(largest.amount)}, which is "
            f"{ratio:.1f}x this customer's established average of {_fmt_inr(baseline)}. "
            f"The transaction settled on {largest.occurred_at:%d %b %Y at %H:%M %Z} via "
            f"{largest.channel}. An amount this far outside a customer's own pattern is "
            "a standard AML review trigger and requires investigation to establish "
            "whether there is a legitimate explanation."
        ),
        severity_score=min(40 + ratio * 4, 95),
        metrics=[
            {"label": "Historical average", "value": _fmt_inr(baseline)},
            {"label": "This transaction", "value": _fmt_inr(largest.amount)},
            {"label": "Deviation", "value": f"{ratio:.1f}x baseline"},
            {"label": "Channel", "value": largest.channel},
        ],
        transaction_refs=[largest.txn_ref],
        rule_code="AMOUNT_DEVIATION",
        transaction_id=largest.id,
    )


def detect_high_velocity(
    customer: Customer, activity: CustomerActivity, threshold_per_hour: float
) -> Optional[Detection]:
    """Densest burst of transactions inside any rolling one-hour window."""
    txns = sorted(activity.recent_all, key=lambda t: t.occurred_at)
    if len(txns) < 3:
        return None

    best_window: List[Transaction] = []
    left = 0
    for right in range(len(txns)):
        while txns[right].occurred_at - txns[left].occurred_at > timedelta(hours=1):
            left += 1
        window = txns[left : right + 1]
        if len(window) > len(best_window):
            best_window = window

    if len(best_window) < threshold_per_hour:
        return None

    span = best_window[-1].occurred_at - best_window[0].occurred_at
    minutes = max(span.total_seconds() / 60.0, 1.0)
    total = sum(t.amount for t in best_window)

    return Detection(
        code="HIGH_VELOCITY",
        name="High transaction velocity",
        headline=f"{len(best_window)} transactions within {minutes:.0f} minutes.",
        explanation=(
            f"{len(best_window)} transactions totalling {_fmt_inr(total)} settled inside "
            f"a {minutes:.0f}-minute window starting "
            f"{best_window[0].occurred_at:%d %b %Y %H:%M %Z}. This exceeds the configured "
            f"velocity threshold of {threshold_per_hour:.0f} transactions per hour. "
            "Activity compressed this tightly is often automated rather than manual and "
            "warrants investigation."
        ),
        severity_score=min(45 + len(best_window) * 2.5, 92),
        metrics=[
            {"label": "Transactions", "value": str(len(best_window))},
            {"label": "Window", "value": f"{minutes:.0f} minutes"},
            {"label": "Total value", "value": _fmt_inr(total)},
            {"label": "Threshold", "value": f"{threshold_per_hour:.0f}/hour"},
        ],
        transaction_refs=[t.txn_ref for t in best_window[:8]],
        rule_code="VELOCITY_THRESHOLD",
        transaction_id=best_window[0].id,
    )


def detect_rapid_movement(
    customer: Customer, bundle_context: Dict[str, Any], score: float, threshold: float
) -> Optional[Detection]:
    if score < threshold:
        return None
    evidence = bundle_context.get("rapid_movement_evidence") or []
    if not evidence:
        return None

    top = evidence[0]
    inbound = float(top["inbound_amount"])
    outbound = float(top["outbound_amount"])
    delay = float(top["delay_minutes"])

    return Detection(
        code="RAPID_FUND_MOVEMENT",
        name="Rapid movement of funds",
        headline=(
            f"{_fmt_inr(inbound)} received, {_fmt_inr(outbound)} transferred out "
            f"{delay:.0f} minute(s) later."
        ),
        explanation=(
            f"Transaction {top['inbound_ref']} credited {_fmt_inr(inbound)}. Within "
            f"{delay:.0f} minute(s), {_fmt_inr(outbound)} "
            f"({top['forwarded_pct']}% of the amount received) left the account across "
            f"{len(top['outbound_refs'])} outbound transfer(s). Across the review window, "
            f"{score * 100:.0f}% of all inbound value was forwarded onward within "
            "30 minutes. An account that retains almost nothing it receives is behaving "
            "as a pass-through, which is a recognised layering indicator."
        ),
        severity_score=min(55 + score * 40, 96),
        metrics=[
            {"label": "Received", "value": _fmt_inr(inbound)},
            {"label": "Forwarded out", "value": _fmt_inr(outbound)},
            {"label": "Delay", "value": f"{delay:.0f} minutes"},
            {"label": "Pass-through rate", "value": f"{score * 100:.0f}%"},
        ],
        transaction_refs=[top["inbound_ref"]] + list(top["outbound_refs"])[:4],
        rule_code="RAPID_FUND_MOVEMENT",
    )


def detect_multiple_counterparties(
    customer: Customer, bundle_values: Dict[str, float], threshold: float
) -> Optional[Detection]:
    new_count = bundle_values.get("new_counterparties_30d", 0.0)
    if new_count < threshold:
        return None
    unique = bundle_values.get("unique_counterparties_30d", 0.0)
    baseline = customer.baseline_counterparties or 0

    return Detection(
        code="MULTIPLE_COUNTERPARTIES",
        name="Multiple new counterparties",
        headline=f"1 account paying out to {int(new_count)} new recipients.",
        explanation=(
            f"{int(new_count)} beneficiaries were seen for the first time in the last 30 "
            f"days, taking this customer to {int(unique)} distinct counterparties against "
            f"an established baseline of {baseline}. A sudden expansion of the payee "
            "network can indicate dispersion of funds through newly recruited accounts, "
            "and requires investigation to confirm whether the relationships are genuine."
        ),
        severity_score=min(40 + new_count * 3.0, 90),
        metrics=[
            {"label": "New beneficiaries (30d)", "value": str(int(new_count))},
            {"label": "Total counterparties", "value": str(int(unique))},
            {"label": "Baseline", "value": str(baseline)},
            {"label": "Threshold", "value": f"{threshold:.0f} new"},
        ],
        transaction_refs=[],
        rule_code="NEW_BENEFICIARY",
    )


def detect_behavioural_anomaly(
    customer: Customer, bundle_context: Dict[str, Any], threshold: float
) -> Optional[Detection]:
    baseline = float(bundle_context.get("baseline_avg_amount", 0.0))
    current = float(bundle_context.get("avg_recent_amount", 0.0))
    if baseline <= 0 or current <= 0:
        return None
    deviation_pct = (current - baseline) / baseline * 100.0
    if deviation_pct < threshold * 100:
        return None

    return Detection(
        code="BEHAVIOURAL_ANOMALY",
        name="Behavioural anomaly",
        headline=(
            f"Average transaction moved from {_fmt_inr(baseline)} to "
            f"{_fmt_inr(current)} ({deviation_pct:+.0f}%)."
        ),
        explanation=(
            f"The customer's average transaction size over the last 30 days is "
            f"{_fmt_inr(current)}, against a historical average of {_fmt_inr(baseline)} - "
            f"a deviation of {deviation_pct:+.0f}%. Sustained drift of this magnitude "
            "indicates the customer's transaction profile has fundamentally changed. "
            "This may have a legitimate explanation (a business change, an asset sale) "
            "and investigation should establish which."
        ),
        severity_score=min(38 + deviation_pct / 25.0, 88),
        metrics=[
            {"label": "Historical average", "value": _fmt_inr(baseline)},
            {"label": "Current average", "value": _fmt_inr(current)},
            {"label": "Deviation", "value": f"{deviation_pct:+.0f}%"},
            {
                "label": "Transactions (30d)",
                "value": str(int(bundle_context.get("recent_outgoing_count", 0)
                              + bundle_context.get("recent_incoming_count", 0))),
            },
        ],
        transaction_refs=[],
        rule_code="BEHAVIOURAL_DEVIATION",
    )


# ---------------------------------------------------------------------------
# Sweep orchestration
# ---------------------------------------------------------------------------


def _threshold(hits_by_code: Dict[str, float], code: str, fallback: float) -> float:
    return hits_by_code.get(code, fallback)


def run_monitoring_sweep(
    db: Session,
    customers: Optional[Sequence[Customer]] = None,
    create_alerts: bool = True,
    reference_time: Optional[datetime] = None,
) -> List[Alert]:
    """Score settled activity for each customer and raise reactive alerts.

    Idempotent: a finding that is already on file (same customer, pattern and
    evidence) refreshes the existing open alert instead of raising a duplicate,
    and a finding an analyst has already closed is not re-raised. Only newly
    created alerts are returned, and only they bump rule trigger counts and the
    customer's prior-alert count.
    """
    reactive_rules = load_rules(db, layer="REACTIVE")
    rules = reactive_rules + load_rules(db, layer="PROACTIVE")
    thresholds = {rule.code: float(rule.threshold) for rule in rules}

    targets: Sequence[Customer] = (
        customers if customers is not None else db.scalars(select(Customer)).all()
    )
    created: List[Alert] = []

    for customer in targets:
        activity = feature_service.load_activity(db, customer, reference_time)
        if not activity.recent_all:
            continue

        bundle = feature_service.extract_features(
            db, customer, reference_time=reference_time
        )
        metrics = feature_service.rule_metrics(bundle)
        hits: List[RuleHit] = evaluate(reactive_rules, metrics)

        detections: List[Detection] = []
        for detection in (
            detect_unusual_amount(
                customer, activity, _threshold(thresholds, "AMOUNT_DEVIATION", 4.0)
            ),
            detect_high_velocity(
                customer, activity, _threshold(thresholds, "VELOCITY_THRESHOLD", 8.0)
            ),
            detect_rapid_movement(
                customer,
                bundle.context,
                bundle.values.get("rapid_movement_score", 0.0),
                _threshold(thresholds, "RAPID_FUND_MOVEMENT", 0.7),
            ),
            detect_multiple_counterparties(
                customer, bundle.values, _threshold(thresholds, "NEW_BENEFICIARY", 5.0)
            ),
            detect_behavioural_anomaly(
                customer,
                bundle.context,
                _threshold(thresholds, "BEHAVIOURAL_DEVIATION", 2.5),
            ),
        ):
            if detection is not None:
                detections.append(detection)

        if not detections:
            continue

        new_for_customer: List[Alert] = []
        if create_alerts:
            for detection in detections:
                alert, is_new = _raise_or_refresh(db, customer, detection, reference_time)
                if is_new and alert is not None:
                    new_for_customer.append(alert)

        if create_alerts and not new_for_customer:
            # Every finding was already on file - nothing new to assess or count
            continue

        fired = {hit.code for hit in hits}
        for rule in reactive_rules:
            if rule.code in fired:
                rule.triggered_count = (rule.triggered_count or 0) + 1

        result = risk_service.score(bundle, hits, explain=True)
        risk_service.persist_assessment(
            db=db,
            result=result,
            kind=AssessmentKind.REACTIVE.value,
            customer=customer,
            assessed_at=reference_time,
            notes=(
                f"Reactive sweep detected {len(detections)} pattern(s): "
                + ", ".join(d.code for d in detections)
            ),
        )
        created.extend(new_for_customer)

    return created


def _raise_or_refresh(
    db: Session,
    customer: Customer,
    detection: Detection,
    reference_time: Optional[datetime],
) -> tuple[Optional[Alert], bool]:
    """Upsert one detection as an alert; mark its transactions when new."""
    # Patterns without concrete transaction evidence (counterparty growth,
    # behavioural drift) are customer-level: one live alert per customer per
    # pattern, and a closed one may be re-raised after a full review window.
    customer_level = not detection.transaction_refs
    alert, is_new = alert_service.upsert_alert(
        db,
        dedupe_key=alert_service.dedupe_key_for(
            "REACTIVE", customer.id, detection.code, detection.transaction_refs
        ),
        suppress_after_close=(
            timedelta(days=DEFAULT_WINDOW_DAYS) if customer_level else None
        ),
        source=AlertSource.REACTIVE.value,
        alert_type=detection.code,
        title=f"{detection.name} - {customer.name} ({customer.customer_ref})",
        explanation=detection.explanation,
        risk_score=detection.severity_score,
        risk_level=settings.risk_level_for(detection.severity_score),
        customer_id=customer.id,
        transaction_id=detection.transaction_id,
        rule_code=detection.rule_code,
        evidence={
            "headline": detection.headline,
            "metrics": detection.metrics,
            "transaction_refs": detection.transaction_refs,
            "layer": "REACTIVE (post-settlement monitoring)",
            "pattern_code": detection.code,
        },
        raised_at=reference_time,
    )

    if is_new and detection.transaction_refs:
        rows = db.scalars(
            select(Transaction).where(Transaction.txn_ref.in_(detection.transaction_refs))
        ).all()
        for row in rows:
            row.has_alert = True
    return alert, is_new


def build_pattern_cards(db: Session, limit: int = 40) -> List[Dict[str, Any]]:
    """Reactive alerts rendered as narrative cards for the monitoring page."""
    alerts: Sequence[Alert] = db.scalars(
        select(Alert)
        .where(Alert.source == AlertSource.REACTIVE.value)
        .order_by(Alert.risk_score.desc(), Alert.raised_at.desc())
        .limit(limit)
    ).all()

    cards: List[Dict[str, Any]] = []
    for alert in alerts:
        evidence = alert.evidence or {}
        cards.append(
            {
                "alert_ref": alert.alert_ref,
                "pattern_code": evidence.get("pattern_code", alert.alert_type),
                "pattern_name": alert.alert_type.replace("_", " ").title(),
                "customer_ref": alert.customer.customer_ref if alert.customer else None,
                "customer_name": alert.customer.name if alert.customer else None,
                "severity": alert.severity,
                "risk_score": alert.risk_score,
                "risk_level": alert.risk_level,
                "status": alert.status,
                "raised_at": alert.raised_at,
                "headline": evidence.get("headline", alert.title),
                "explanation": alert.explanation,
                "metrics": evidence.get("metrics", []),
                "transaction_refs": evidence.get("transaction_refs", []),
            }
        )
    return cards
