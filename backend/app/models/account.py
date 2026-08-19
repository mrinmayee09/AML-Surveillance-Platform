"""Accounts, wallets and merchant settlement accounts - the graph node table."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base_mixins import TimestampMixin


class Account(Base, TimestampMixin):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_ref: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    display_name: Mapped[str] = mapped_column(String(128))
    entity_type: Mapped[str] = mapped_column(String(24), default="ACCOUNT", index=True)
    institution: Mapped[str] = mapped_column(String(64), default="Meridian Bank")
    ifsc: Mapped[Optional[str]] = mapped_column(String(16))
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    country: Mapped[str] = mapped_column(String(64), default="India")
    city: Mapped[str] = mapped_column(String(64), default="Mumbai")

    balance: Mapped[float] = mapped_column(Float, default=0.0)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=True)
    is_dormant: Mapped[bool] = mapped_column(Boolean, default=False)
    opened_days_ago: Mapped[int] = mapped_column(Integer, default=365)

    # --- Denormalised graph metrics, refreshed by the graph engine ---------
    risk_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW")
    total_in: Mapped[float] = mapped_column(Float, default=0.0)
    total_out: Mapped[float] = mapped_column(Float, default=0.0)
    degree_in: Mapped[int] = mapped_column(Integer, default=0)
    degree_out: Mapped[int] = mapped_column(Integer, default=0)

    customer: Mapped[Optional["Customer"]] = relationship(
        "Customer", back_populates="accounts"
    )
    outgoing: Mapped[List["Transaction"]] = relationship(
        "Transaction",
        back_populates="sender_account",
        foreign_keys="Transaction.sender_account_id",
    )
    incoming: Mapped[List["Transaction"]] = relationship(
        "Transaction",
        back_populates="receiver_account",
        foreign_keys="Transaction.receiver_account_id",
    )

    @property
    def volume(self) -> float:
        return (self.total_in or 0.0) + (self.total_out or 0.0)

    @property
    def degree(self) -> int:
        return (self.degree_in or 0) + (self.degree_out or 0)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Account {self.account_ref}>"
