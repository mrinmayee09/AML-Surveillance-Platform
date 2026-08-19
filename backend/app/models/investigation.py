"""Investigation case files and their notes/timeline."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base_mixins import TimestampMixin


class Investigation(Base, TimestampMixin):
    __tablename__ = "investigations"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_ref: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[Optional[str]] = mapped_column(Text, default="")

    alert_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("alerts.id"), nullable=True, index=True
    )
    customer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("customers.id"), nullable=True, index=True
    )
    network_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("networks.id"), nullable=True, index=True
    )

    status: Mapped[str] = mapped_column(String(24), default="OPEN", index=True)
    priority: Mapped[str] = mapped_column(String(16), default="MEDIUM", index=True)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    assignee_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Set only when a human analyst records a conclusion
    outcome: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)

    alert: Mapped[Optional["Alert"]] = relationship("Alert", back_populates="investigations")
    customer: Mapped[Optional["Customer"]] = relationship(
        "Customer", back_populates="investigations"
    )
    network: Mapped[Optional["Network"]] = relationship("Network")
    assignee: Mapped[Optional["User"]] = relationship(
        "User", back_populates="investigations", foreign_keys=[assignee_id]
    )
    notes: Mapped[List["InvestigationNote"]] = relationship(
        "InvestigationNote",
        back_populates="investigation",
        cascade="all, delete-orphan",
        order_by="InvestigationNote.created_at",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Investigation {self.case_ref} {self.status}>"


class InvestigationNote(Base, TimestampMixin):
    __tablename__ = "investigation_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    author_name: Mapped[str] = mapped_column(String(128), default="system")
    # NOTE | STATUS_CHANGE | ASSIGNMENT | ESCALATION | SYSTEM
    note_type: Mapped[str] = mapped_column(String(24), default="NOTE")
    body: Mapped[str] = mapped_column(Text)

    investigation: Mapped["Investigation"] = relationship(
        "Investigation", back_populates="notes"
    )
