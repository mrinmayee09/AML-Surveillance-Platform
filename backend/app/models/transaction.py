"""Transactions - the graph edge table and the unit of AML monitoring."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base_mixins import TimestampMixin


class Transaction(Base, TimestampMixin):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_txn_sender_time", "sender_account_id", "occurred_at"),
        Index("ix_txn_receiver_time", "receiver_account_id", "occurred_at"),
        Index("ix_txn_risk", "risk_level", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    txn_ref: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    sender_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    receiver_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"), nullable=True)

    # The settled amount. Always derived server-side.
    amount: Mapped[float] = mapped_column(Float, index=True)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    channel: Mapped[str] = mapped_column(String(16), default="UPI", index=True)
    txn_type: Mapped[str] = mapped_column(String(16), default="TRANSFER")
    status: Mapped[str] = mapped_column(String(16), default="COMPLETED", index=True)

    city: Mapped[str] = mapped_column(String(64), default="Mumbai")
    country: Mapped[str] = mapped_column(String(64), default="India")
    is_international: Mapped[bool] = mapped_column(Boolean, default=False)
    device_fingerprint: Mapped[Optional[str]] = mapped_column(String(64))
    narrative: Mapped[Optional[str]] = mapped_column(String(255))

    # --- Risk outputs ------------------------------------------------------
    risk_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW", index=True)
    # Which layer scored it: PROACTIVE (pre-transaction) or REACTIVE (post-hoc)
    scored_by: Mapped[str] = mapped_column(String(16), default="REACTIVE")
    decision: Mapped[str] = mapped_column(String(16), default="ALLOW")
    integrity_status: Mapped[str] = mapped_column(String(24), default="VERIFIED")
    # Amount the client claimed, retained purely for forensic comparison.
    claimed_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    has_alert: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    triggered_rules: Mapped[Optional[str]] = mapped_column(Text, default="")

    # Set by the graph engine when the edge falls inside a flagged subgraph
    network_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("networks.id"), nullable=True, index=True
    )
    is_suspicious_edge: Mapped[bool] = mapped_column(Boolean, default=False)

    sender_account: Mapped["Account"] = relationship(
        "Account", back_populates="outgoing", foreign_keys=[sender_account_id]
    )
    receiver_account: Mapped["Account"] = relationship(
        "Account", back_populates="incoming", foreign_keys=[receiver_account_id]
    )
    order: Mapped[Optional["Order"]] = relationship("Order", back_populates="transactions")
    alerts: Mapped[List["Alert"]] = relationship("Alert", back_populates="transaction")
    network: Mapped[Optional["Network"]] = relationship("Network")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Transaction {self.txn_ref} {self.amount}>"
