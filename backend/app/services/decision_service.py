"""The pre-transaction decision pipeline.

Implements the nine ordered steps the platform runs before any payment is
allowed to settle:

  1. Validate order                  (does a server-side order exist?)
  2. Retrieve server-side amount     (the authoritative value)
  3. Validate amount integrity       (client claim vs server truth)
  4. Calculate behavioural features  (from the customer's real history)
  5. Run the proactive risk model
  6. Generate the composite risk score
  7. Apply decision rules            (configurable thresholds)
  8. Allow / Monitor / Review / Block
  9. Record an audit event

Steps 1-3 are a hard gate: an integrity failure blocks the payment regardless of
how low the AML risk score is. The two concerns are kept separate on purpose -
"was this request tampered with" and "is this customer behaving suspiciously" are
different questions with different remedies.
"""

from __future__ import annotations

import time
import uuid

from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.types import utcnow
from app.models import Account, Customer, Order, Transaction
from app.models.enums import (
    AssessmentKind,
    Decision,
    IntegrityStatus,
    OrderStatus,
    TransactionStatus,
)
from app.rules.engine import evaluate, load_behavioural_rules, load_rules
from app.schemas.transaction import (
    GatewayDecision,
    IntegrityCheck,
    PaymentIntentRequest,
    PipelineStep,
)
from app.services import audit_service, feature_service, integrity_service, risk_service
from app.services.audit_service import Actor

# The payment provider is deliberately NOT integrated. This string is surfaced in
# the API response so nothing in the UI can be mistaken for a real settlement.
PROVIDER_NOTE_ALLOWED = (
    "SIMULATED: no payment provider is integrated. In production this is where the "
    "server-authorised amount would be handed to the provider SDK. The amount "
    "forwarded is always the server-side value, never the client's claim."
)
PROVIDER_NOTE_BLOCKED = (
    "SIMULATED: no request was made to any payment provider. The payment was "
    "stopped at the gateway."
)


class _Clock:
    """Millisecond timer for per-step pipeline timings."""

    def __init__(self) -> None:
        self._last = time.perf_counter()

    def lap(self) -> float:
        now = time.perf_counter()
        elapsed = (now - self._last) * 1000.0
        self._last = now
        return round(elapsed, 2)


def _step(
    key: str, label: str, status: str, detail: str, value: Optional[str], ms: float
) -> PipelineStep:
    return PipelineStep(
        key=key, label=label, status=status, detail=detail, value=value, duration_ms=ms
    )


def _skipped(key: str, label: str, reason: str) -> PipelineStep:
    return PipelineStep(key=key, label=label, status="SKIPPED", detail=reason)


def _integrity_failure_response(
    request_id: str,
    payload: PaymentIntentRequest,
    check: IntegrityCheck,
    pipeline: List[PipelineStep],
    customer_ref: Optional[str],
) -> GatewayDecision:
    """Blocked at the integrity gate: no AML scoring is performed or implied."""
    from app.schemas.common import ModelProvenance

    for key, label in (
        ("features", "Behaviour analysis"),
        ("model", "AML risk model"),
        ("score", "AML risk score"),
        ("rules", "Decision rules"),
    ):
        pipeline.append(
            _skipped(key, label, "Not evaluated - the request failed integrity validation.")
        )

    return GatewayDecision(
        request_id=request_id,
        order_ref=payload.order_ref,
        customer_ref=customer_ref,
        decision=Decision.BLOCK.value,
        risk_score=100.0,
        risk_level="CRITICAL",
        integrity=check,
        pipeline=pipeline,
        factors=[],
        features={},
        triggered_rules=[
            "INTEGRITY_AMOUNT_MISMATCH"
            if check.status == IntegrityStatus.AMOUNT_MISMATCH.value
            else "INTEGRITY_DIGEST_INVALID"
        ]
        if check.status
        in {IntegrityStatus.AMOUNT_MISMATCH.value, IntegrityStatus.REPLAY_DETECTED.value}
        else [],
        provenance=ModelProvenance(
            model_name="integrity_gateway",
            model_version="1.0.0",
            model_type="Deterministic server-side validation (no model involved)",
            trained=False,
            training_data="Not applicable - this is an exact comparison, not a prediction.",
            notes=(
                "The integrity gate is deterministic. It compares the client's claimed "
                "amount against orders.authorized_amount and verifies an HMAC digest. "
                "No machine learning is used or needed."
            ),
        ),
        transaction_ref=None,
        alert_ref=None,
        amount_forwarded=None,
        payment_provider_note=PROVIDER_NOTE_BLOCKED,
        advisory=(
            "This payment was blocked by a deterministic server-side integrity check, "
            "not by a risk model. The client-supplied amount was rejected; the "
            "server-authorised amount is unchanged."
        ),
        evaluated_at=utcnow(),
    )


def run_gateway(
    db: Session,
    payload: PaymentIntentRequest,
    actor: Actor,
    settle_if_allowed: bool = True,
) -> GatewayDecision:
    """Execute the full pre-transaction pipeline for one payment intent."""
    request_id = f"REQ-{uuid.uuid4().hex[:12].upper()}"
    clock = _Clock()
    pipeline: List[PipelineStep] = []

    # ---- Steps 1-3: order lookup, authoritative amount, integrity --------
    check, order = integrity_service.validate_payment_request(
        db=db,
        order_ref=payload.order_ref,
        claimed_amount=payload.claimed_amount,
        claimed_currency=payload.claimed_currency,
        claimed_customer_ref=payload.customer_ref,
    )
    integrity_ms = clock.lap()

    order_found = order is not None
    pipeline.append(
        _step(
            "order",
            "Order validation",
            "PASS" if order_found else "FAIL",
            f"Server-side order record located for {payload.order_ref}."
            if order_found
            else f"No server-side order exists for {payload.order_ref}.",
            payload.order_ref,
            integrity_ms,
        )
    )

    if not order_found:
        audit_service.record(
            db,
            actor,
            action="GATEWAY_BLOCKED",
            resource_type="ORDER",
            resource_ref=payload.order_ref,
            new_state="BLOCKED",
            detail=check.message,
            context={"request_id": request_id, "reason": check.status},
        )
        db.commit()
        return _integrity_failure_response(request_id, payload, check, pipeline, None)

    assert order is not None
    customer: Customer = order.customer

    pipeline.append(
        _step(
            "authoritative_amount",
            "Server-side amount retrieval",
            "PASS",
            "Authoritative amount read from orders.authorized_amount. The client "
            "value is never used as the amount to charge.",
            f"{order.currency} {order.authorized_amount:,.2f}",
            0.0,
        )
    )
    pipeline.append(
        _step(
            "integrity",
            "Amount integrity",
            "PASS" if check.passed else "FAIL",
            check.message,
            f"claimed {check.received_currency} {check.received_amount:,.2f} vs "
            f"authorised {check.authorized_currency} {check.authorized_amount:,.2f}",
            integrity_ms,
        )
    )

    if not check.passed:
        if check.status == IntegrityStatus.AMOUNT_MISMATCH.value:
            order.status = OrderStatus.INTEGRITY_FAILED.value
        audit_service.record(
            db,
            actor,
            action="GATEWAY_BLOCKED",
            resource_type="ORDER",
            resource_ref=order.order_ref,
            previous_state=order.status,
            new_state="BLOCKED",
            detail=check.message,
            context={
                "request_id": request_id,
                "reason": check.status,
                "authorized_amount": check.authorized_amount,
                "claimed_amount": check.received_amount,
                "mismatch_amount": check.mismatch_amount,
            },
        )
        db.commit()
        return _integrity_failure_response(
            request_id, payload, check, pipeline, customer.customer_ref
        )

    # ---- Step 4: behavioural features ------------------------------------
    authorised_amount = integrity_service.authoritative_amount(order)
    bundle = feature_service.extract_features(
        db=db,
        customer=customer,
        # Scored against the AUTHORITATIVE amount, not the client's claim
        prospective_amount=authorised_amount,
    )
    features_ms = clock.lap()

    velocity_label = str(bundle.context.get("velocity_label", "LOW"))
    deviation = bundle.values.get("amount_deviation_ratio", 1.0)
    pipeline.append(
        _step(
            "features",
            "Behaviour analysis",
            "WARN" if (deviation >= 3.0 or velocity_label == "HIGH") else "PASS",
            f"Computed {len(bundle.values)} behavioural features from "
            f"{int(bundle.context.get('total_transactions', 0))} historical transactions. "
            f"Amount is {deviation:.1f}x the customer baseline; velocity {velocity_label}.",
            f"{deviation:.1f}x baseline",
            features_ms,
        )
    )

    # ---- Steps 5-6: model + composite score ------------------------------
    metrics = feature_service.rule_metrics(bundle)
    rules = load_behavioural_rules(db)
    hits = evaluate(rules, metrics, increment_counts=True)
    trend = risk_service.determine_trend(db, customer, 0.0)
    result = risk_service.score(bundle, hits, trend=trend)
    # Recompute the trend now the score is known
    result.trend = risk_service.determine_trend(db, customer, result.score)
    model_ms = clock.lap()

    provenance = result.provenance
    pipeline.append(
        _step(
            "model",
            "AML risk model",
            "PASS" if (result.model_probability or 0) < 0.5 else "WARN",
            (
                f"{provenance.model_type} returned P(elevated risk) = "
                f"{result.model_probability:.3f}."
                if provenance
                else "Model executed."
            )
            + (
                ""
                if provenance and provenance.trained
                else " NOTE: no trained artifact is loaded; an untrained fallback scorer produced this value."
            ),
            f"p={result.model_probability:.3f}" if result.model_probability else None,
            model_ms,
        )
    )
    pipeline.append(
        _step(
            "score",
            "AML risk score",
            "PASS"
            if result.level == "LOW"
            else "WARN"
            if result.level in {"MEDIUM", "HIGH"}
            else "FAIL",
            f"Composite score {result.score}/100 ({result.level}), blending the model "
            f"({int(risk_service.MODEL_WEIGHT * 100)}%) with "
            f"{len(hits)} fired rule(s) ({int(risk_service.RULES_WEIGHT * 100)}%).",
            f"{result.score:.0f}/100",
            0.0,
        )
    )

    # ---- Step 7: decision rules ------------------------------------------
    decision = result.decision
    rule_names = ", ".join(hit.code for hit in hits) or "none"
    pipeline.append(
        _step(
            "rules",
            "Decision rules",
            "PASS"
            if decision == Decision.ALLOW.value
            else "WARN"
            if decision in {Decision.MONITOR.value, Decision.REVIEW.value}
            else "FAIL",
            f"Thresholds MEDIUM>={settings.risk_threshold_medium}, "
            f"HIGH>={settings.risk_threshold_high}, "
            f"CRITICAL>={settings.risk_threshold_critical} -> {decision}. "
            f"Rules fired: {rule_names}.",
            decision,
            clock.lap(),
        )
    )

    # ---- Step 8: act on the decision -------------------------------------
    transaction_ref: Optional[str] = None
    alert_ref: Optional[str] = None
    amount_forwarded: Optional[float] = None

    settled = decision in {Decision.ALLOW.value, Decision.MONITOR.value}
    if settle_if_allowed and settled:
        txn = _create_transaction(
            db=db,
            order=order,
            customer=customer,
            amount=authorised_amount,
            channel=payload.channel,
            risk_score=result.score,
            risk_level=result.level,
            decision=decision,
            claimed_amount=payload.claimed_amount,
            device_fingerprint=payload.device_fingerprint,
            triggered=result.triggered_rule_codes,
        )
        transaction_ref = txn.txn_ref
        amount_forwarded = authorised_amount
        order.status = OrderStatus.PAID.value
    elif settle_if_allowed:
        # REVIEW / BLOCK: the order stays unpaid and a held transaction records
        # the attempt for the investigator.
        txn = _create_transaction(
            db=db,
            order=order,
            customer=customer,
            amount=authorised_amount,
            channel=payload.channel,
            risk_score=result.score,
            risk_level=result.level,
            decision=decision,
            claimed_amount=payload.claimed_amount,
            device_fingerprint=payload.device_fingerprint,
            triggered=result.triggered_rule_codes,
            status=(
                TransactionStatus.BLOCKED.value
                if decision == Decision.BLOCK.value
                else TransactionStatus.HELD.value
            ),
        )
        transaction_ref = txn.txn_ref

    db.flush()

    txn_id = None
    if transaction_ref:
        txn_row = db.scalar(select(Transaction).where(Transaction.txn_ref == transaction_ref))
        txn_id = txn_row.id if txn_row else None

    risk_service.persist_assessment(
        db=db,
        result=result,
        kind=AssessmentKind.PROACTIVE.value,
        customer=customer,
        transaction_id=txn_id,
        notes=f"Pre-transaction assessment for order {order.order_ref}.",
    )

    # An alert is raised whenever the decision is not a clean allow
    if decision in {Decision.REVIEW.value, Decision.BLOCK.value}:
        from app.services import alert_service

        alert = alert_service.raise_proactive_alert(
            db=db,
            customer=customer,
            result=result,
            transaction_id=txn_id,
            order_ref=order.order_ref,
        )
        alert_ref = alert.alert_ref
        if txn_id:
            txn_row = db.get(Transaction, txn_id)
            if txn_row:
                txn_row.has_alert = True

    # ---- Step 9: audit ---------------------------------------------------
    audit_service.record(
        db,
        actor,
        action=f"GATEWAY_{decision}",
        resource_type="ORDER",
        resource_ref=order.order_ref,
        previous_state=OrderStatus.AWAITING_PAYMENT.value,
        new_state=order.status,
        detail=(
            f"Pre-transaction decision {decision} at risk {result.score}/100 "
            f"({result.level}). Amount forwarded: "
            + (f"{order.currency} {amount_forwarded:,.2f}" if amount_forwarded else "none")
        ),
        context={
            "request_id": request_id,
            "risk_score": result.score,
            "risk_level": result.level,
            "decision": decision,
            "authorized_amount": authorised_amount,
            "claimed_amount": payload.claimed_amount,
            "triggered_rules": result.triggered_rule_codes,
            "transaction_ref": transaction_ref,
            "alert_ref": alert_ref,
        },
    )
    db.commit()

    return GatewayDecision(
        request_id=request_id,
        order_ref=order.order_ref,
        customer_ref=customer.customer_ref,
        decision=decision,
        risk_score=result.score,
        risk_level=result.level,
        integrity=check,
        pipeline=pipeline,
        factors=result.factors,
        features=result.features,
        triggered_rules=result.triggered_rule_codes,
        provenance=provenance,  # type: ignore[arg-type]
        transaction_ref=transaction_ref,
        alert_ref=alert_ref,
        amount_forwarded=amount_forwarded,
        payment_provider_note=(
            PROVIDER_NOTE_ALLOWED if amount_forwarded else PROVIDER_NOTE_BLOCKED
        ),
        advisory=risk_service.RISK_ADVISORY,
        evaluated_at=utcnow(),
    )


def _create_transaction(
    db: Session,
    order: Order,
    customer: Customer,
    amount: float,
    channel: str,
    risk_score: float,
    risk_level: str,
    decision: str,
    claimed_amount: Optional[float],
    device_fingerprint: Optional[str],
    triggered: List[str],
    status: str = TransactionStatus.COMPLETED.value,
) -> Transaction:
    """Persist the transaction using the SERVER-SIDE amount only."""
    sender = customer.accounts[0] if customer.accounts else None
    receiver = (
        db.get(Account, order.merchant_account_id) if order.merchant_account_id else None
    )
    if sender is None or receiver is None:
        raise ValueError(
            f"Order {order.order_ref} cannot settle: missing sender or merchant account"
        )

    txn = Transaction(
        txn_ref=f"TXN-{uuid.uuid4().hex[:12].upper()}",
        occurred_at=utcnow(),
        sender_account_id=sender.id,
        receiver_account_id=receiver.id,
        order_id=order.id,
        amount=amount,  # authoritative value
        currency=order.currency,
        channel=channel,
        txn_type="PAYMENT",
        status=status,
        city=sender.city,
        country=sender.country,
        is_international=sender.country != receiver.country,
        device_fingerprint=device_fingerprint,
        narrative=f"Payment for order {order.order_ref} ({order.merchant_name})",
        risk_score=risk_score,
        risk_level=risk_level,
        scored_by="PROACTIVE",
        decision=decision,
        integrity_status=IntegrityStatus.VERIFIED.value,
        claimed_amount=claimed_amount,
        triggered_rules=",".join(triggered),
    )
    db.add(txn)
    return txn


def analyze_only(
    db: Session, customer: Customer, amount: float, country: str = "India"
) -> Tuple[risk_service.RiskResult, dict]:
    """Score a hypothetical transaction without creating or settling anything."""
    bundle = feature_service.extract_features(
        db=db, customer=customer, prospective_amount=amount, prospective_country=country
    )
    metrics = feature_service.rule_metrics(bundle)
    hits = evaluate(load_behavioural_rules(db), metrics)
    trend = risk_service.determine_trend(db, customer, 0.0)
    result = risk_service.score(bundle, hits, trend=trend)
    return result, bundle.context
