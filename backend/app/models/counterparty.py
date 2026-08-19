"""Counterparty relationships.

A materialised view of "who does this customer transact with", including when
the relationship was first seen. New-beneficiary detection reads this table.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base_mixins import TimestampMixin


class Counterparty(Base, TimestampMixin):
    __tablename__ = "counterparties"
    __table_args__ = (
        UniqueConstraint("customer_id", "account_id", name="uq_counterparty_pair"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    relationship_type: Mapped[str] = mapped_column(String(24), default="BENEFICIARY")

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime)
    txn_count: Mapped[int] = mapped_column(Integer, default=0)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)
    # True while first_seen_at is inside the new-beneficiary window (30 days)
    is_new: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    country: Mapped[str] = mapped_column(String(64), default="India")

    account: Mapped["Account"] = relationship("Account")
    customer: Mapped["Customer"] = relationship("Customer")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Counterparty cust={self.customer_id} acct={self.account_id}>"
