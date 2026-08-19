"""Commerce orders.

`authorized_amount` is the SERVER-SIDE SOURCE OF TRUTH used by the transaction
integrity gateway. A payment request arriving from any client is validated
against this column; the client-supplied amount is never trusted, stored as
authoritative, or forwarded to a payment provider.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base_mixins import TimestampMixin


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_ref: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    merchant_name: Mapped[str] = mapped_column(String(128))
    merchant_account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )
    description: Mapped[str] = mapped_column(String(255), default="")

    # --- Server-authoritative money fields --------------------------------
    authorized_amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    # HMAC digest over (order_ref, authorized_amount, currency, customer_ref).
    # Lets the gateway detect tampering of the stored row itself.
    integrity_digest: Mapped[str] = mapped_column(String(64), default="")

    status: Mapped[str] = mapped_column(
        String(24), default="AWAITING_PAYMENT", index=True
    )

    customer: Mapped["Customer"] = relationship("Customer", back_populates="orders")
    transactions: Mapped[List["Transaction"]] = relationship(
        "Transaction", back_populates="order"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Order {self.order_ref} {self.currency} {self.authorized_amount}>"
