"""Transaction endpoints: listing, detail, and the pre-transaction gateway."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.core.deps import get_actor, get_current_user, require_gateway
from app.db.base import SessionLocal, get_db
from app.models import Account, Customer, Order, Transaction, User
from app.models.enums import OrderStatus
from app.schemas.common import Page
from app.schemas.transaction import (
    GatewayDecision,
    IntegrityCheck,
    OrderSummary,
    PaymentIntentRequest,
    TransactionAnalyzeRequest,
    TransactionAnalyzeResponse,
    TransactionDetail,
    TransactionListItem,
)
from app.services import decision_service, gnn_v2_service, integrity_service, risk_service
from app.services.audit_service import Actor

router = APIRouter(prefix="/transactions", tags=["transactions"])

SortField = str


def _row_to_list_item(
    txn: Transaction, sender: Account, receiver: Account
) -> TransactionListItem:
    return TransactionListItem(
        id=txn.id,
        txn_ref=txn.txn_ref,
        occurred_at=txn.occurred_at,
        amount=txn.amount,
        currency=txn.currency,
        channel=txn.channel,
        txn_type=txn.txn_type,
        status=txn.status,
        city=txn.city,
        country=txn.country,
        is_international=txn.is_international,
        risk_score=txn.risk_score,
        risk_level=txn.risk_level,
        decision=txn.decision,
        integrity_status=txn.integrity_status,
        has_alert=txn.has_alert,
        scored_by=txn.scored_by,
        sender_ref=sender.account_ref if sender else "",
        sender_name=sender.display_name if sender else "",
        receiver_ref=receiver.account_ref if receiver else "",
        receiver_name=receiver.display_name if receiver else "",
        network_ref=txn.network.network_ref if txn.network else None,
    )


@router.get("", response_model=Page[TransactionListItem])
def list_transactions(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    search: Optional[str] = Query(None, max_length=64, description="Txn ref, account or name"),
    risk_level: Optional[str] = Query(None, pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$"),
    channel: Optional[str] = Query(None, max_length=16),
    txn_status: Optional[str] = Query(None, alias="status", max_length=16),
    customer_ref: Optional[str] = Query(None, max_length=32),
    has_alert: Optional[bool] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    min_amount: Optional[float] = Query(None, ge=0),
    max_amount: Optional[float] = Query(None, ge=0),
    sort_by: SortField = Query("occurred_at", pattern="^(occurred_at|amount|risk_score)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """Filterable, sortable, paginated transaction list."""
    sender = aliased(Account)
    receiver = aliased(Account)

    stmt = (
        select(Transaction, sender, receiver)
        .join(sender, Transaction.sender_account_id == sender.id)
        .join(receiver, Transaction.receiver_account_id == receiver.id)
    )
    count_stmt = (
        select(func.count(Transaction.id))
        .join(sender, Transaction.sender_account_id == sender.id)
        .join(receiver, Transaction.receiver_account_id == receiver.id)
    )

    filters = []
    if search:
        like = f"%{search}%"
        filters.append(
            or_(
                Transaction.txn_ref.ilike(like),
                sender.account_ref.ilike(like),
                receiver.account_ref.ilike(like),
                sender.display_name.ilike(like),
                receiver.display_name.ilike(like),
            )
        )
    if risk_level:
        filters.append(Transaction.risk_level == risk_level)
    if channel:
        filters.append(Transaction.channel == channel.upper())
    if txn_status:
        filters.append(Transaction.status == txn_status.upper())
    if has_alert is not None:
        filters.append(Transaction.has_alert.is_(has_alert))
    if date_from:
        filters.append(Transaction.occurred_at >= date_from)
    if date_to:
        filters.append(Transaction.occurred_at <= date_to)
    if min_amount is not None:
        filters.append(Transaction.amount >= min_amount)
    if max_amount is not None:
        filters.append(Transaction.amount <= max_amount)
    if customer_ref:
        customer = db.scalar(select(Customer).where(Customer.customer_ref == customer_ref))
        if customer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": f"No customer {customer_ref}."},
            )
        account_ids = [a.id for a in customer.accounts]
        filters.append(
            or_(
                Transaction.sender_account_id.in_(account_ids),
                Transaction.receiver_account_id.in_(account_ids),
            )
        )

    for condition in filters:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = int(db.scalar(count_stmt) or 0)
    column = {
        "occurred_at": Transaction.occurred_at,
        "amount": Transaction.amount,
        "risk_score": Transaction.risk_score,
    }[sort_by]
    stmt = stmt.order_by(column.desc() if sort_dir == "desc" else column.asc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    rows = db.execute(stmt).all()
    items = [_row_to_list_item(txn, snd, rcv) for txn, snd, rcv in rows]
    pages = max((total + page_size - 1) // page_size, 1)

    return Page[TransactionListItem](
        items=items, total=total, page=page, page_size=page_size, pages=pages
    )


@router.get("/orders", response_model=List[OrderSummary])
def list_orders(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    order_status: Optional[str] = Query(None, alias="status", max_length=24),
    limit: int = Query(25, ge=1, le=100),
):
    """Orders available to the gateway demo, with their authoritative amounts."""
    stmt = select(Order).order_by(Order.created_at.desc())
    if order_status:
        stmt = stmt.where(Order.status == order_status.upper())
    rows = db.scalars(stmt.limit(limit)).all()
    return [
        OrderSummary(
            id=o.id,
            order_ref=o.order_ref,
            merchant_name=o.merchant_name,
            description=o.description,
            authorized_amount=o.authorized_amount,
            currency=o.currency,
            status=o.status,
            created_at=o.created_at,
            customer_ref=o.customer.customer_ref if o.customer else "",
            customer_name=o.customer.name if o.customer else "",
        )
        for o in rows
    ]


@router.post("/validate", response_model=IntegrityCheck)
def validate_transaction(
    payload: PaymentIntentRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_gateway),
):
    """Integrity check ONLY - compares the client claim against server truth.

    Performs no AML scoring and creates nothing. Useful for demonstrating the
    integrity gate in isolation.
    """
    check, _order = integrity_service.validate_payment_request(
        db=db,
        order_ref=payload.order_ref,
        claimed_amount=payload.claimed_amount,
        claimed_currency=payload.claimed_currency,
        claimed_customer_ref=payload.customer_ref,
    )
    return check


@router.post("/analyze", response_model=TransactionAnalyzeResponse)
def analyze_transaction(
    payload: TransactionAnalyzeRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_gateway),
):
    """Score a hypothetical transaction without creating or settling anything."""
    customer = db.scalar(
        select(Customer).where(Customer.customer_ref == payload.customer_ref)
    )
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "not_found",
                "message": f"No customer {payload.customer_ref}.",
            },
        )

    result, _context = decision_service.analyze_only(
        db, customer, payload.amount, payload.country
    )
    return TransactionAnalyzeResponse(
        customer_ref=customer.customer_ref,
        risk_score=result.score,
        risk_level=result.level,
        decision=result.decision,
        model_probability=result.model_probability,
        factors=result.factors,
        features=result.features,
        triggered_rules=result.triggered_rule_codes,
        provenance=result.provenance,  # type: ignore[arg-type]
        advisory=risk_service.RISK_ADVISORY,
    )


@router.post("/decision", response_model=GatewayDecision)
def transaction_decision(
    payload: PaymentIntentRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _: User = Depends(require_gateway),
):
    """Run the FULL pre-transaction pipeline and act on the decision.

    This is the endpoint the Security Gateway page calls. It performs the
    integrity check, computes features, scores risk, applies decision rules,
    settles or holds the payment, raises an alert where warranted, and writes an
    audit entry.
    """
    try:
        decision = decision_service.run_gateway(db, payload, actor, settle_if_allowed=True)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "cannot_settle", "message": str(exc)},
        ) from exc
    # Reactive network layer: once money has actually moved, score both parties'
    # neighbourhoods with the window GNN - after the response, so it never delays
    # the payment.
    if decision.transaction_ref and decision.amount_forwarded is not None:
        background.add_task(_score_settled_parties, decision.transaction_ref)
    return decision


def _score_settled_parties(txn_ref: str) -> None:
    if gnn_v2_service.get_model() is None:
        return
    with SessionLocal() as db:
        txn = db.scalar(select(Transaction).where(Transaction.txn_ref == txn_ref))
        if txn is None:
            return
        refs = [txn.sender_account.account_ref, txn.receiver_account.account_ref]
        gnn_v2_service.score_accounts(db, refs, window_end=txn.occurred_at)
        db.commit()


@router.get("/{txn_ref}", response_model=TransactionDetail)
def get_transaction(
    txn_ref: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Full transaction detail, including peer context for the drawer."""
    txn = db.scalar(select(Transaction).where(Transaction.txn_ref == txn_ref))
    if txn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"No transaction {txn_ref}."},
        )

    sender = db.get(Account, txn.sender_account_id)
    receiver = db.get(Account, txn.receiver_account_id)
    base = _row_to_list_item(txn, sender, receiver)

    # Peer context: how this transaction compares with the sender's own history
    peer_avg = float(
        db.scalar(
            select(func.avg(Transaction.amount)).where(
                Transaction.sender_account_id == txn.sender_account_id
            )
        )
        or 0.0
    )
    channel_avg = float(
        db.scalar(
            select(func.avg(Transaction.amount)).where(Transaction.channel == txn.channel)
        )
        or 0.0
    )

    # The explainable factors recorded when this transaction was scored
    from app.models import RiskAssessment

    assessment = db.scalar(
        select(RiskAssessment)
        .where(RiskAssessment.transaction_id == txn.id)
        .order_by(RiskAssessment.assessed_at.desc())
        .limit(1)
    )
    factors = assessment.factors if assessment and assessment.factors else []

    return TransactionDetail(
        **base.model_dump(),
        narrative=txn.narrative,
        device_fingerprint=txn.device_fingerprint,
        claimed_amount=txn.claimed_amount,
        triggered_rules=[c for c in (txn.triggered_rules or "").split(",") if c],
        order_ref=txn.order.order_ref if txn.order else None,
        sender_customer_ref=(
            sender.customer.customer_ref if sender and sender.customer else None
        ),
        receiver_customer_ref=(
            receiver.customer.customer_ref if receiver and receiver.customer else None
        ),
        is_suspicious_edge=txn.is_suspicious_edge,
        risk_factors=factors,
        peer_context={
            "sender_avg_amount": round(peer_avg, 2),
            "ratio_to_sender_avg": round(txn.amount / peer_avg, 2) if peer_avg else None,
            "channel_avg_amount": round(channel_avg, 2),
            "ratio_to_channel_avg": round(txn.amount / channel_avg, 2)
            if channel_avg
            else None,
            "assessment_ref": assessment.assessment_ref if assessment else None,
            "model_probability": assessment.model_probability if assessment else None,
        },
    )
