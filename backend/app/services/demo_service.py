"""End-to-end demo orchestration.

Runs the platform's whole narrative as one coherent story rather than a set of
disconnected pages:

    payment intent -> integrity gate -> proactive AML -> decision -> settlement
    -> reactive monitoring -> graph engine -> GNN -> suspicious network
    -> alert -> investigation -> investigator note

Every step performs REAL work against the live database - the same services the
individual pages call. Each step returns the route where the investigator can go
and verify the result for themselves.
"""

from __future__ import annotations

import time
import uuid

from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.types import utcnow
from app.models import (
    Account,
    Alert,
    Customer,
    Investigation,
    Network,
    Order,
    Transaction,
    User,
)
from app.models.enums import AlertStatus, OrderStatus
from app.schemas.transaction import PaymentIntentRequest
from app.services import (
    alert_service,
    audit_service,
    decision_service,
    integrity_service,
    investigation_service,
    network_service,
    reactive_service,
)
from app.services.audit_service import Actor

DEMO_ADVISORY = (
    "This walkthrough executed real pipeline logic against the demo database. The "
    "underlying data is synthetic and no payment provider was contacted. Risk scores "
    "and network findings are model-generated indicators for human review, not "
    "determinations of criminal conduct."
)

SCENARIOS = {
    "LAYERED_RING": {
        "label": "Layered movement network",
        "description": (
            "A legitimate-looking retail payment clears, then reactive monitoring and "
            "the graph engine surface a layering chain the customer participates in."
        ),
    },
    "TAMPERED_AMOUNT": {
        "label": "Payment tampering attempt",
        "description": (
            "A client submits a payment request with an inflated amount. The integrity "
            "gateway blocks it using the server-authorised value."
        ),
    },
}


class _Recorder:
    """Accumulates demo steps with timings."""

    def __init__(self) -> None:
        self.steps: List[Dict[str, Any]] = []
        self._t0 = time.perf_counter()

    def add(
        self,
        key: str,
        title: str,
        layer: str,
        status: str,
        summary: str,
        detail: Optional[Dict[str, Any]] = None,
        route: Optional[str] = None,
    ) -> None:
        now = time.perf_counter()
        self.steps.append(
            {
                "index": len(self.steps) + 1,
                "key": key,
                "title": title,
                "layer": layer,
                "status": status,
                "summary": summary,
                "detail": detail or {},
                "route": route,
                "duration_ms": round((now - self._t0) * 1000.0, 2),
            }
        )
        self._t0 = now


def _pick_demo_order(db: Session, prefer_high_risk: bool) -> Optional[Order]:
    """An unpaid order, preferring one belonging to an elevated-risk customer."""
    stmt = (
        select(Order)
        .join(Customer, Order.customer_id == Customer.id)
        .where(Order.status == OrderStatus.AWAITING_PAYMENT.value)
    )
    if prefer_high_risk:
        stmt = stmt.order_by(Customer.current_risk_score.desc())
    else:
        stmt = stmt.order_by(Customer.current_risk_score.asc())
    return db.scalar(stmt.limit(1))


def run_demo(
    db: Session,
    actor: Actor,
    scenario: str = "LAYERED_RING",
    claimed_amount: Optional[float] = None,
) -> Dict[str, Any]:
    """Execute the end-to-end AML narrative."""
    scenario = scenario.upper()
    if scenario not in SCENARIOS:
        scenario = "LAYERED_RING"

    run_ref = f"DEMO-{uuid.uuid4().hex[:8].upper()}"
    started_at = utcnow()
    rec = _Recorder()

    tampering = scenario == "TAMPERED_AMOUNT"
    order = _pick_demo_order(db, prefer_high_risk=not tampering)

    if order is None:
        rec.add(
            "no_data",
            "No payable order available",
            "SETUP",
            "FAIL",
            "The demo needs at least one order in AWAITING_PAYMENT. Re-run the seed script.",
        )
        return {
            "run_ref": run_ref,
            "scenario": scenario,
            "started_at": started_at,
            "finished_at": utcnow(),
            "steps": rec.steps,
            "outcome": {"status": "ABORTED", "reason": "no payable order"},
            "advisory": DEMO_ADVISORY,
        }

    customer: Customer = order.customer
    authorised = float(order.authorized_amount)

    # ---- Step 1: customer initiates a payment ---------------------------
    submitted = (
        float(claimed_amount)
        if claimed_amount is not None
        else (authorised * 10 if tampering else authorised)
    )
    rec.add(
        "initiate",
        "Customer initiates payment",
        "CLIENT",
        "PASS",
        (
            f"{customer.name} ({customer.customer_ref}) checks out order "
            f"{order.order_ref} for {order.currency} {authorised:,.2f} with "
            f"{order.merchant_name}."
        ),
        {
            "order_ref": order.order_ref,
            "customer_ref": customer.customer_ref,
            "merchant": order.merchant_name,
            "displayed_amount": authorised,
            "client_submitted_amount": submitted,
            "tampered": tampering,
            "note": (
                "The client request was modified in transit to inflate the amount."
                if tampering
                else "The client request matches what the customer was shown."
            ),
        },
        route="/gateway",
    )

    # ---- Steps 2-8: the gateway pipeline --------------------------------
    payload = PaymentIntentRequest(
        order_ref=order.order_ref,
        claimed_amount=submitted,
        claimed_currency=order.currency,
        customer_ref=customer.customer_ref,
        channel="UPI",
        device_fingerprint="demo-device-8f21c",
    )
    decision = decision_service.run_gateway(db, payload, actor, settle_if_allowed=True)

    integrity = decision.integrity
    rec.add(
        "integrity",
        "Transaction integrity validation",
        "INTEGRITY",
        "PASS" if integrity.passed else "FAIL",
        integrity.message,
        {
            "server_authorized_amount": integrity.authorized_amount,
            "client_claimed_amount": integrity.received_amount,
            "mismatch_amount": integrity.mismatch_amount,
            "mismatch_pct": integrity.mismatch_pct,
            "source_of_truth": integrity.source_of_truth,
            "digest_valid": integrity.digest_valid,
            "status": integrity.status,
        },
        route="/gateway",
    )

    if not integrity.passed:
        # The tampering scenario legitimately ends here: nothing settles, so
        # there is no downstream AML activity to show.
        rec.add(
            "blocked",
            "Payment blocked at the gateway",
            "INTEGRITY",
            "FAIL",
            (
                "The payment was refused before any AML scoring took place. The "
                "client-supplied amount was discarded; the server-authorised amount "
                "was never charged and no request reached a payment provider."
            ),
            {
                "decision": decision.decision,
                "payment_provider_note": decision.payment_provider_note,
                "audit_action": "GATEWAY_BLOCKED",
            },
            route="/audit-logs",
        )
        db.commit()
        return {
            "run_ref": run_ref,
            "scenario": scenario,
            "started_at": started_at,
            "finished_at": utcnow(),
            "steps": rec.steps,
            "outcome": {
                "status": "BLOCKED_AT_INTEGRITY",
                "order_ref": order.order_ref,
                "expected_amount": integrity.authorized_amount,
                "received_amount": integrity.received_amount,
                "mismatch_amount": integrity.mismatch_amount,
                "decision": decision.decision,
            },
            "advisory": DEMO_ADVISORY,
        }

    rec.add(
        "proactive",
        "Proactive AML analyses the customer",
        "PROACTIVE",
        "WARN" if decision.risk_level in {"MEDIUM", "HIGH", "CRITICAL"} else "PASS",
        (
            f"Behavioural features computed server-side from the customer's own "
            f"history. {decision.provenance.model_name} scored the payment at "
            f"{decision.risk_score}/100 ({decision.risk_level}), blending the model "
            f"with {len(decision.triggered_rules)} fired rule(s)."
        ),
        {
            "risk_score": decision.risk_score,
            "risk_level": decision.risk_level,
            "model": decision.provenance.model_name,
            "model_trained": decision.provenance.trained,
            "top_factors": [f.model_dump() for f in decision.factors[:5]],
            "triggered_rules": decision.triggered_rules,
        },
        route=f"/customers/{customer.customer_ref}",
    )

    rec.add(
        "decision",
        "Risk decision applied",
        "PROACTIVE",
        "PASS" if decision.decision in {"ALLOW", "MONITOR"} else "FAIL",
        (
            f"Decision rules resolved the {decision.risk_level} score to "
            f"{decision.decision}."
        ),
        {
            "decision": decision.decision,
            "pipeline": [s.model_dump() for s in decision.pipeline],
        },
        route="/gateway",
    )

    settled = decision.transaction_ref is not None and decision.amount_forwarded is not None
    rec.add(
        "payment",
        "Payment proceeds" if settled else "Payment held",
        "PAYMENT",
        "PASS" if settled else "WARN",
        (
            f"The SERVER-AUTHORISED amount {order.currency} "
            f"{decision.amount_forwarded:,.2f} was forwarded. "
            f"Transaction {decision.transaction_ref} recorded."
            if settled
            else (
                f"The payment was not settled ({decision.decision}). Transaction "
                f"{decision.transaction_ref} was recorded in a held state for review."
            )
        ),
        {
            "transaction_ref": decision.transaction_ref,
            "amount_forwarded": decision.amount_forwarded,
            "payment_provider_note": decision.payment_provider_note,
        },
        route="/transactions",
    )

    rec.add(
        "database",
        "Transaction enters the monitoring database",
        "REACTIVE",
        "PASS",
        (
            f"Transaction {decision.transaction_ref} is now in scope for "
            "post-settlement reactive monitoring and graph construction."
        ),
        {"transaction_ref": decision.transaction_ref},
        route="/transactions",
    )

    # ---- Step 9: reactive monitoring ------------------------------------
    reactive_alerts = reactive_service.run_monitoring_sweep(
        db, customers=[customer], create_alerts=True
    )
    db.flush()
    rec.add(
        "reactive",
        "Reactive monitoring analyses settled activity",
        "REACTIVE",
        "WARN" if reactive_alerts else "PASS",
        (
            f"The reactive sweep detected {len(reactive_alerts)} pattern(s) for this "
            f"customer: " + ", ".join(a.alert_type for a in reactive_alerts)
            if reactive_alerts
            else "The reactive sweep found no post-settlement pattern for this customer."
        ),
        {
            "alerts": [
                {
                    "alert_ref": a.alert_ref,
                    "type": a.alert_type,
                    "risk_score": a.risk_score,
                    "headline": (a.evidence or {}).get("headline", ""),
                }
                for a in reactive_alerts
            ]
        },
        route="/reactive",
    )

    # ---- Step 10: graph engine + GNN ------------------------------------
    networks = network_service.analyse_graph(db, persist=True)
    db.flush()
    suspicious = [n for n in networks if n.is_suspicious]
    rec.add(
        "graph",
        "Graph engine rebuilds the financial network",
        "NETWORK",
        "PASS",
        (
            f"Constructed the transaction graph and detected {len(networks)} candidate "
            f"cluster(s) using structural typology analysis."
        ),
        {
            "clusters_detected": len(networks),
            "patterns": sorted({n.pattern for n in networks}),
        },
        route="/network",
    )

    from app.gnn.registry import get_gnn_engine

    engine = get_gnn_engine()
    top_network: Optional[Network] = (
        max(suspicious, key=lambda n: n.risk_score) if suspicious else None
    )
    rec.add(
        "gnn",
        "GNN scores the network",
        "NETWORK",
        "WARN" if suspicious else "PASS",
        (
            f"{'The trained graph neural network' if engine.trained else 'The analytic graph engine (untrained)'} "
            f"scored every node, edge and cluster. {len(suspicious)} cluster(s) exceeded "
            f"the suspicious threshold."
            + (
                f" Highest: {top_network.network_ref} at {top_network.risk_score}/100 "
                f"({top_network.pattern})."
                if top_network
                else ""
            )
        ),
        {
            "engine": engine.name,
            "engine_trained": engine.trained,
            "architecture": engine.architecture,
            "suspicious_networks": [
                {
                    "network_ref": n.network_ref,
                    "pattern": n.pattern,
                    "risk_score": n.risk_score,
                    "node_count": n.node_count,
                    "edge_count": n.edge_count,
                    "total_flow": n.total_flow,
                    "signals": [s["label"] for s in (n.signals or [])[:5]],
                }
                for n in sorted(suspicious, key=lambda n: n.risk_score, reverse=True)[:5]
            ],
        },
        route="/network",
    )

    # ---- Step 11: network alerts ----------------------------------------
    network_alerts = network_service.raise_network_alerts(db, suspicious)
    db.flush()
    anchor_alert: Optional[Alert] = None
    if network_alerts:
        anchor_alert = max(network_alerts, key=lambda a: a.risk_score)
    elif reactive_alerts:
        anchor_alert = max(reactive_alerts, key=lambda a: a.risk_score)
    elif decision.alert_ref:
        anchor_alert = db.scalar(select(Alert).where(Alert.alert_ref == decision.alert_ref))

    # Detection is idempotent, so a repeat walkthrough re-detects findings that
    # are already on file instead of raising new ones. Pick up the strongest of
    # those that is still untouched (NEW), so the case-handling steps still run.
    reused_existing = False
    if anchor_alert is None:
        network_ids = [n.id for n in suspicious if n.id is not None]
        anchor_alert = db.scalar(
            select(Alert)
            .where(
                Alert.status == AlertStatus.NEW.value,
                (Alert.customer_id == customer.id) | Alert.network_id.in_(network_ids),
            )
            .order_by(Alert.risk_score.desc())
            .limit(1)
        )
        reused_existing = anchor_alert is not None

    rec.add(
        "alert",
        "Alert created",
        "NETWORK",
        "WARN" if anchor_alert else "PASS",
        (
            (
                f"No new finding - alert {anchor_alert.alert_ref} is already on file "
                f"for this activity and was refreshed: {anchor_alert.title}"
                if reused_existing
                else f"Alert {anchor_alert.alert_ref} raised: {anchor_alert.title}"
            )
            if anchor_alert
            else "No alert was raised by this run."
        ),
        {
            "network_alerts": [a.alert_ref for a in network_alerts],
            "anchor_alert_ref": anchor_alert.alert_ref if anchor_alert else None,
            "reused_existing_alert": reused_existing,
            "risk_score": anchor_alert.risk_score if anchor_alert else None,
        },
        route="/alerts",
    )

    if anchor_alert is None:
        db.commit()
        return {
            "run_ref": run_ref,
            "scenario": scenario,
            "started_at": started_at,
            "finished_at": utcnow(),
            "steps": rec.steps,
            "outcome": {
                "status": "COMPLETED_NO_ALERT",
                "transaction_ref": decision.transaction_ref,
                "decision": decision.decision,
                "risk_score": decision.risk_score,
            },
            "advisory": DEMO_ADVISORY,
        }

    # ---- Step 12: investigator opens the alert --------------------------
    alert_service.transition(
        db,
        anchor_alert,
        AlertStatus.UNDER_REVIEW.value,
        actor,
        note="Opened for review as part of the end-to-end walkthrough.",
    )
    db.flush()
    rec.add(
        "open_alert",
        "Investigator opens the alert",
        "INVESTIGATION",
        "PASS",
        (
            f"Alert {anchor_alert.alert_ref} moved NEW -> UNDER_REVIEW. The transition "
            "was written to the audit log."
        ),
        {
            "alert_ref": anchor_alert.alert_ref,
            "status": anchor_alert.status,
            "explanation": anchor_alert.explanation[:600],
        },
        route=f"/alerts/{anchor_alert.alert_ref}",
    )

    # ---- Step 13: case file with the network + history ------------------
    investigation = investigation_service.create_investigation(
        db=db,
        title=f"Review of {anchor_alert.alert_type} - {anchor_alert.alert_ref}",
        actor=actor,
        alert=anchor_alert,
        customer=anchor_alert.customer or customer,
        network=anchor_alert.network,
        priority="HIGH" if anchor_alert.risk_score >= 70 else "MEDIUM",
        summary=(
            "Case opened by the end-to-end walkthrough. Aggregates the proactive "
            "assessment, reactive pattern findings and the network detection for "
            "analyst review."
        ),
    )
    db.flush()

    detail = investigation_service.build_detail(db, investigation)
    rec.add(
        "investigate",
        "Investigator reviews the network and history",
        "INVESTIGATION",
        "PASS",
        (
            f"Case {investigation.case_ref} opened. The workspace aggregates "
            f"{len(detail['alerts'])} alert(s), {len(detail['linked_transactions'])} "
            f"transaction(s), {len(detail['risk_factors'])} explained risk factor(s)"
            + (
                f" and the {anchor_alert.network.network_ref} network graph."
                if anchor_alert.network
                else "."
            )
        ),
        {
            "case_ref": investigation.case_ref,
            "alert_count": len(detail["alerts"]),
            "transaction_count": len(detail["linked_transactions"]),
            "risk_factor_count": len(detail["risk_factors"]),
            "network_ref": (
                anchor_alert.network.network_ref if anchor_alert.network else None
            ),
            "network_stats": (
                detail["network_snapshot"]["stats"] if detail["network_snapshot"] else None
            ),
        },
        route=f"/investigations/{investigation.case_ref}",
    )

    # ---- Step 14: investigator note -------------------------------------
    note_body = (
        f"Reviewed the {anchor_alert.alert_type} finding for "
        f"{(anchor_alert.customer or customer).customer_ref}. "
        + (
            f"Network {anchor_alert.network.network_ref} shows a "
            f"{anchor_alert.network.pattern} topology across "
            f"{anchor_alert.network.node_count} accounts with a total flow of "
            f"{anchor_alert.network.total_flow:,.2f}. "
            if anchor_alert.network
            else ""
        )
        + "Requesting source-of-funds documentation and counterparty verification "
        "before reaching any conclusion. Model output treated as a prioritisation "
        "signal only, not as evidence."
    )
    # Attribute the note to the acting user where we can resolve them
    author = (
        db.scalar(select(User).where(User.username == actor.username))
        if actor.username
        else None
    )
    investigation_service.record_note(
        db=db,
        investigation=investigation,
        body=note_body,
        author=author,
        actor=actor,
        note_type="NOTE",
    )

    audit_service.record(
        db,
        actor,
        action="DEMO_RUN_COMPLETED",
        resource_type="DEMO",
        resource_ref=run_ref,
        new_state="COMPLETED",
        detail=f"End-to-end walkthrough completed for scenario {scenario}.",
        context={
            "order_ref": order.order_ref,
            "transaction_ref": decision.transaction_ref,
            "alert_ref": anchor_alert.alert_ref,
            "case_ref": investigation.case_ref,
        },
    )
    db.commit()

    rec.add(
        "note",
        "Investigator adds a note",
        "INVESTIGATION",
        "PASS",
        (
            f"Note recorded on {investigation.case_ref} and written to the audit log. "
            "The case remains open pending human determination."
        ),
        {"case_ref": investigation.case_ref, "note": note_body},
        route=f"/investigations/{investigation.case_ref}",
    )

    return {
        "run_ref": run_ref,
        "scenario": scenario,
        "started_at": started_at,
        "finished_at": utcnow(),
        "steps": rec.steps,
        "outcome": {
            "status": "COMPLETED",
            "order_ref": order.order_ref,
            "customer_ref": customer.customer_ref,
            "transaction_ref": decision.transaction_ref,
            "decision": decision.decision,
            "risk_score": decision.risk_score,
            "risk_level": decision.risk_level,
            "alert_ref": anchor_alert.alert_ref,
            "network_ref": (
                anchor_alert.network.network_ref if anchor_alert.network else None
            ),
            "case_ref": investigation.case_ref,
            "suspicious_networks": len(suspicious),
        },
        "advisory": DEMO_ADVISORY,
    }
