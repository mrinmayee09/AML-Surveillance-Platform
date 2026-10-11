"""Scores from the window GNN (GraphSAGE trained on IBM AMLworld).

One row per account per scoring run: the probability, whether it crossed the
model's validation-chosen threshold, and the transfers the score depended on
(occlusion explanation), so the UI and alerts can show WHY an account was flagged.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime
from app.models.base_mixins import TimestampMixin


class GnnAccountScore(Base, TimestampMixin):
    __tablename__ = "gnn_account_scores"
    __table_args__ = (Index("ix_gnn_score_account_time", "account_id", "window_end"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    window_end: Mapped[datetime] = mapped_column(UTCDateTime, index=True)

    score: Mapped[float] = mapped_column(Float)  # probability 0-1
    threshold: Mapped[float] = mapped_column(Float)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    window_nodes: Mapped[int] = mapped_column(Integer, default=0)
    window_edges: Mapped[int] = mapped_column(Integer, default=0)
    model_name: Mapped[str] = mapped_column(String(64))
    model_variant: Mapped[str] = mapped_column(String(16))
    # [{rank, txn_ref, sender, receiver, amount, currency, occurred_at, score_drop}]
    top_transfers: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON, default=list)
    alert_id: Mapped[Optional[int]] = mapped_column(ForeignKey("alerts.id"), nullable=True)

    account: Mapped["Account"] = relationship("Account")
