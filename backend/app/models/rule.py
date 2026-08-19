"""Configurable AML detection rules.

Rules are data, not code paths: each row carries the threshold and weight that
`app.rules.engine` evaluates. Admins can enable/disable and re-tune them
without a redeploy.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import JSON, Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base_mixins import TimestampMixin


class Rule(Base, TimestampMixin):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), default="BEHAVIOURAL", index=True)
    severity: Mapped[str] = mapped_column(String(16), default="MEDIUM", index=True)
    # Which layer consumes this rule: PROACTIVE | REACTIVE | NETWORK | INTEGRITY
    layer: Mapped[str] = mapped_column(String(16), default="REACTIVE", index=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # Primary numeric threshold + comparison operator (GT, GTE, LT, LTE)
    threshold: Mapped[float] = mapped_column(Float, default=0.0)
    operator: Mapped[str] = mapped_column(String(8), default="GTE")
    threshold_unit: Mapped[str] = mapped_column(String(24), default="")
    # Points this rule contributes to the composite score when it fires
    score_weight: Mapped[float] = mapped_column(Float, default=10.0)
    # Extra named parameters (e.g. window_minutes)
    params: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, default=dict)

    triggered_count: Mapped[int] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Rule {self.code} enabled={self.enabled}>"
