"""Append-only audit trail.

Every state-changing action (login, alert transition, note, rule toggle,
gateway decision) writes one row. Rows are never updated or deleted.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)

    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    actor: Mapped[str] = mapped_column(String(64), default="system", index=True)
    actor_role: Mapped[str] = mapped_column(String(16), default="SYSTEM")

    action: Mapped[str] = mapped_column(String(64), index=True)
    resource_type: Mapped[str] = mapped_column(String(32), index=True)
    resource_ref: Mapped[str] = mapped_column(String(48), index=True)

    previous_state: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    new_state: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, default="")
    context: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, default=dict)

    ip_address: Mapped[str] = mapped_column(String(64), default="127.0.0.1")
    session_id: Mapped[str] = mapped_column(String(64), default="")

    user: Mapped[Optional["User"]] = relationship("User", back_populates="audit_logs")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditLog {self.action} {self.resource_ref}>"
