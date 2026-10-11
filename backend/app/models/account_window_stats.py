"""Per-account window statistics for the reactive graph layer.

A materialised cache of `app.graph.features_v2.compute_account_stats`: one row
per account and window length, holding the raw measurements (for explanations
and the UI) and the account-level feature vector (for the GNN). It is derived
data - always recomputable from `transactions` - and records the feature schema
version and window it was computed for, so a stale or outdated row is
detectable rather than silently reused.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime
from app.models.base_mixins import TimestampMixin


class AccountWindowStats(Base, TimestampMixin):
    __tablename__ = "account_window_stats"
    __table_args__ = (
        UniqueConstraint("account_id", "window_days", name="uq_account_window"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    window_days: Mapped[int] = mapped_column(Integer, default=7)
    schema_version: Mapped[str] = mapped_column(String(16))
    window_start: Mapped[datetime] = mapped_column(UTCDateTime)
    window_end: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    # Latest settled transfer the stats include; a newer one means the row is stale
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)

    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    features: Mapped[list[float]] = mapped_column(JSON, default=list)

    account: Mapped["Account"] = relationship("Account")
