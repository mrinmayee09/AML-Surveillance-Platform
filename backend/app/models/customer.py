"""Bank customers - the subject of proactive behavioural risk scoring."""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from sqlalchemy import Boolean, Date, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base_mixins import TimestampMixin


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_ref: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(32))
    entity_type: Mapped[str] = mapped_column(String(24), default="CUSTOMER")

    # --- KYC / onboarding -------------------------------------------------
    onboarded_on: Mapped[date] = mapped_column(Date)
    account_age_years: Mapped[float] = mapped_column(Float, default=1.0)
    kyc_level: Mapped[str] = mapped_column(String(16), default="FULL")
    pep_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    occupation: Mapped[Optional[str]] = mapped_column(String(64))
    city: Mapped[str] = mapped_column(String(64), default="Mumbai")
    country: Mapped[str] = mapped_column(String(64), default="India")
    # Share of activity touching higher-risk jurisdictions (0.0 - 1.0)
    risk_country_exposure: Mapped[float] = mapped_column(Float, default=0.0)

    # --- Behavioural baseline maintained by the aggregation layer ---------
    baseline_avg_amount: Mapped[float] = mapped_column(Float, default=0.0)
    baseline_monthly_count: Mapped[float] = mapped_column(Float, default=0.0)
    baseline_counterparties: Mapped[int] = mapped_column(Integer, default=0)

    # --- Latest risk snapshot (denormalised for fast dashboard reads) -----
    current_risk_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    current_risk_level: Mapped[str] = mapped_column(String(16), default="LOW", index=True)
    risk_trend: Mapped[str] = mapped_column(String(16), default="STABLE")
    under_monitoring: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    previous_alert_count: Mapped[int] = mapped_column(Integer, default=0)

    # Generator archetype. Used ONLY as a weak label for model training and
    # evaluation in this prototype. It is never surfaced as an accusation.
    seed_archetype: Mapped[str] = mapped_column(String(32), default="NORMAL")

    accounts: Mapped[List["Account"]] = relationship(
        "Account", back_populates="customer", cascade="all, delete-orphan"
    )
    orders: Mapped[List["Order"]] = relationship("Order", back_populates="customer")
    risk_assessments: Mapped[List["RiskAssessment"]] = relationship(
        "RiskAssessment", back_populates="customer", cascade="all, delete-orphan"
    )
    alerts: Mapped[List["Alert"]] = relationship("Alert", back_populates="customer")
    investigations: Mapped[List["Investigation"]] = relationship(
        "Investigation", back_populates="customer"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Customer {self.customer_ref} {self.name}>"
