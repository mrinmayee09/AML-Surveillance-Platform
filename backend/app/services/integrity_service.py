"""Transaction integrity gateway.

THE CENTRAL SECURITY PROPERTY OF THIS MODULE
--------------------------------------------
The authoritative payment amount is read from `orders.authorized_amount` in the
database. The amount supplied by the client is treated as an untrusted claim: it
is used only for comparison and forensic logging, and is NEVER

  * used as the amount to charge,
  * written into a transaction as the settled amount, or
  * forwarded to a payment provider.

So a client that manipulates INR 8,000 into INR 80,000 changes nothing about what
would be charged - it only produces an integrity failure and a blocked payment.

A second layer verifies an HMAC digest over the stored order fields, so tampering
with the database row itself is also detectable.
"""

from __future__ import annotations

import hmac
from datetime import datetime
from hashlib import sha256
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Customer, Order
from app.models.enums import IntegrityStatus, OrderStatus
from app.schemas.transaction import IntegrityCheck

# Amounts are compared in paise to avoid float-equality problems on money.
AMOUNT_TOLERANCE = 0.01

SOURCE_OF_TRUTH = "server:orders.authorized_amount"


def compute_order_digest(
    order_ref: str, amount: float, currency: str, customer_ref: str
) -> str:
    """HMAC-SHA256 over the order's money-bearing fields.

    Keyed with SECRET_KEY, which lives only in the backend environment. A client
    cannot compute or forge this value.
    """
    payload = f"{order_ref}|{amount:.2f}|{currency.upper()}|{customer_ref}"
    return hmac.new(
        settings.secret_key.encode("utf-8"), payload.encode("utf-8"), sha256
    ).hexdigest()


def verify_order_digest(order: Order, customer_ref: str) -> bool:
    """True when the stored row still matches its digest."""
    if not order.integrity_digest:
        # Legacy/unsigned rows: report explicitly rather than silently passing
        return False
    expected = compute_order_digest(
        order.order_ref, order.authorized_amount, order.currency, customer_ref
    )
    return hmac.compare_digest(expected, order.integrity_digest)


def load_order(db: Session, order_ref: str) -> Optional[Order]:
    return db.scalar(select(Order).where(Order.order_ref == order_ref))


def validate_payment_request(
    db: Session,
    order_ref: str,
    claimed_amount: float,
    claimed_currency: str = "INR",
    claimed_customer_ref: Optional[str] = None,
) -> Tuple[IntegrityCheck, Optional[Order]]:
    """Compare an untrusted payment request against server-side truth.

    Returns the check result and the order (when found). The caller must refuse
    to proceed unless `IntegrityCheck.passed` is True.
    """
    order = load_order(db, order_ref)

    # --- Order must exist -------------------------------------------------
    if order is None:
        return (
            IntegrityCheck(
                status=IntegrityStatus.ORDER_NOT_FOUND.value,
                passed=False,
                order_ref=order_ref,
                authorized_amount=0.0,
                authorized_currency="",
                received_amount=round(claimed_amount, 2),
                received_currency=claimed_currency.upper(),
                mismatch_amount=0.0,
                mismatch_pct=0.0,
                digest_valid=False,
                message=(
                    f"No server-side order exists for reference {order_ref}. "
                    "Payment creation refused - there is no authoritative amount "
                    "to validate against."
                ),
                source_of_truth=SOURCE_OF_TRUTH,
            ),
            None,
        )

    customer: Customer = order.customer
    authorized = float(order.authorized_amount)
    received = float(claimed_amount)
    mismatch = round(received - authorized, 2)
    mismatch_pct = round((mismatch / authorized * 100.0) if authorized else 0.0, 2)
    digest_valid = verify_order_digest(order, customer.customer_ref)

    base = dict(
        order_ref=order.order_ref,
        authorized_amount=round(authorized, 2),
        authorized_currency=order.currency,
        received_amount=round(received, 2),
        received_currency=claimed_currency.upper(),
        mismatch_amount=abs(mismatch),
        mismatch_pct=mismatch_pct,
        digest_valid=digest_valid,
        source_of_truth=SOURCE_OF_TRUTH,
    )

    # --- Stored row must not have been tampered with ----------------------
    if not digest_valid:
        return (
            IntegrityCheck(
                status=IntegrityStatus.REPLAY_DETECTED.value,
                passed=False,
                message=(
                    "The stored order record failed its HMAC integrity check. The "
                    "order row may have been altered outside the application. "
                    "Payment creation refused pending review."
                ),
                **base,
            ),
            order,
        )

    # --- Order must be in a payable state ---------------------------------
    if order.status not in {
        OrderStatus.AWAITING_PAYMENT.value,
        OrderStatus.CREATED.value,
    }:
        return (
            IntegrityCheck(
                status=IntegrityStatus.ORDER_NOT_PAYABLE.value,
                passed=False,
                message=(
                    f"Order {order.order_ref} is in state {order.status} and is not "
                    "payable. This blocks duplicate or replayed payment attempts."
                ),
                **base,
            ),
            order,
        )

    # --- Claimed customer must own the order ------------------------------
    if claimed_customer_ref and claimed_customer_ref != customer.customer_ref:
        return (
            IntegrityCheck(
                status=IntegrityStatus.CUSTOMER_MISMATCH.value,
                passed=False,
                message=(
                    "The customer in the payment request does not own this order. "
                    "Payment creation refused."
                ),
                **base,
            ),
            order,
        )

    # --- Currency must match ----------------------------------------------
    if claimed_currency.upper() != order.currency.upper():
        return (
            IntegrityCheck(
                status=IntegrityStatus.CURRENCY_MISMATCH.value,
                passed=False,
                message=(
                    f"Currency mismatch: order is denominated in {order.currency} but "
                    f"the request claimed {claimed_currency.upper()}."
                ),
                **base,
            ),
            order,
        )

    # --- The amount check -------------------------------------------------
    if abs(mismatch) > AMOUNT_TOLERANCE:
        direction = "inflated" if mismatch > 0 else "reduced"
        return (
            IntegrityCheck(
                status=IntegrityStatus.AMOUNT_MISMATCH.value,
                passed=False,
                message=(
                    f"TRANSACTION INTEGRITY FAILURE. The request {direction} the amount "
                    f"by {order.currency} {abs(mismatch):,.2f} "
                    f"({abs(mismatch_pct):.1f}%). Expected {order.currency} "
                    f"{authorized:,.2f} from the server-side order record; received "
                    f"{order.currency} {received:,.2f} from the client. The client "
                    "value is rejected, not applied."
                ),
                **base,
            ),
            order,
        )

    return (
        IntegrityCheck(
            status=IntegrityStatus.VERIFIED.value,
            passed=True,
            message=(
                f"Verified. The requested amount matches the server-authorised "
                f"{order.currency} {authorized:,.2f} for order {order.order_ref}, and "
                "the order record passed its integrity digest check."
            ),
            **base,
        ),
        order,
    )


def authoritative_amount(order: Order) -> float:
    """The ONLY value that may be charged or settled."""
    return float(order.authorized_amount)


def sign_order(order: Order, customer_ref: str) -> Order:
    """Stamp (or refresh) an order's integrity digest."""
    order.integrity_digest = compute_order_digest(
        order.order_ref, order.authorized_amount, order.currency, customer_ref
    )
    return order


def integrity_metrics(check: IntegrityCheck) -> dict:
    """Metrics dict for the INTEGRITY-layer rules."""
    return {
        "amount_mismatch": float(check.mismatch_amount),
        "digest_invalid": 0.0 if check.digest_valid else 1.0,
    }
