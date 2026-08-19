"""AML alerts raised by the proactive, reactive, network or integrity layers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base_mixins import TimestampMixin


class Alert(Base, TimestampMixin):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_ref: Mapped[str] = mapped_column(String(32), unique=True, index=True)

    # Detector metadata
    source: Mapped[str] = mapped_column(String(16), default="REACTIVE", index=True)
    alert_type: Mapped[str] = mapped_column(String(48), index=True)
    title: Mapped[str] = mapped_column(String(160))
    # Investigator-facing explanation of WHY this fired
    explanation: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, default=dict)
    rule_code: Mapped[Optional[str]] = mapped_column(String(48), index=True)

    customer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("customers.id"), nullable=True, index=True
    )
    transaction_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("transactions.id"), nullable=True, index=True
    )
    account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )
    network_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("networks.id"), nullable=True, index=True
    )

    risk_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="MEDIUM", index=True)
    severity: Mapped[str] = mapped_column(String(16), default="MEDIUM")

    status: Mapped[str] = mapped_column(String(24), default="NEW", index=True)
    assignee_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    raised_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    disposition_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    customer: Mapped[Optional["Customer"]] = relationship(
        "Customer", back_populates="alerts"
    )
    transaction: Mapped[Optional["Transaction"]] = relationship(
        "Transaction", back_populates="alerts"
    )
    network: Mapped[Optional["Network"]] = relationship("Network", back_populates="alerts")
    assignee: Mapped[Optional["User"]] = relationship("User")
    investigations: Mapped[List["Investigation"]] = relationship(
        "Investigation", back_populates="alert"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Alert {self.alert_ref} {self.alert_type} {self.status}>"
