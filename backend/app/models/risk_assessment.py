"""Immutable risk assessment records.

Every scoring event - proactive, reactive or network - is written here so the
platform keeps a full explainable history rather than only a current score.
`factors` holds the additive contribution breakdown shown to investigators.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base_mixins import TimestampMixin


class RiskAssessment(Base, TimestampMixin):
    __tablename__ = "risk_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_ref: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), default="PROACTIVE", index=True)

    customer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    transaction_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("transactions.id"), nullable=True, index=True
    )
    network_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("networks.id"), nullable=True, index=True
    )

    assessed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    risk_score: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(16), index=True)
    trend: Mapped[str] = mapped_column(String(16), default="STABLE")
    decision: Mapped[str] = mapped_column(String(16), default="ALLOW")

    # Provenance of the number - lets the UI state honestly what produced it.
    model_name: Mapped[str] = mapped_column(String(64), default="proactive_rf")
    model_version: Mapped[str] = mapped_column(String(24), default="1.0.0")
    # Raw model probability before calibration to the 0-100 band
    model_probability: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    features: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, default=dict)
    factors: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON, default=list)
    notes: Mapped[Optional[str]] = mapped_column(String(512), default="")

    customer: Mapped[Optional["Customer"]] = relationship(
        "Customer", back_populates="risk_assessments"
    )
    transaction: Mapped[Optional["Transaction"]] = relationship("Transaction")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RiskAssessment {self.assessment_ref} {self.kind} {self.risk_score}>"
