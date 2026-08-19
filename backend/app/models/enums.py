"""Domain enumerations shared by models, schemas and services."""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover
        return self.value


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskTrend(StrEnum):
    DECREASING = "DECREASING"
    STABLE = "STABLE"
    INCREASING = "INCREASING"


class Decision(StrEnum):
    ALLOW = "ALLOW"
    MONITOR = "MONITOR"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class AssessmentKind(StrEnum):
    """Which of the three surveillance layers produced an assessment."""

    PROACTIVE = "PROACTIVE"
    REACTIVE = "REACTIVE"
    NETWORK = "NETWORK"


class EntityType(StrEnum):
    CUSTOMER = "CUSTOMER"
    ACCOUNT = "ACCOUNT"
    MERCHANT = "MERCHANT"
    COMPANY = "COMPANY"
    WALLET = "WALLET"
    BENEFICIARY = "BENEFICIARY"


class Channel(StrEnum):
    UPI = "UPI"
    NEFT = "NEFT"
    RTGS = "RTGS"
    IMPS = "IMPS"
    CARD = "CARD"
    WALLET = "WALLET"
    CASH = "CASH"
    SWIFT = "SWIFT"


class TransactionType(StrEnum):
    TRANSFER = "TRANSFER"
    PAYMENT = "PAYMENT"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"


class TransactionStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    HELD = "HELD"
    BLOCKED = "BLOCKED"
    REVERSED = "REVERSED"


class OrderStatus(StrEnum):
    CREATED = "CREATED"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    INTEGRITY_FAILED = "INTEGRITY_FAILED"


class AlertStatus(StrEnum):
    NEW = "NEW"
    UNDER_REVIEW = "UNDER_REVIEW"
    ESCALATED = "ESCALATED"
    CLEARED = "CLEARED"
    CONFIRMED_SUSPICIOUS = "CONFIRMED_SUSPICIOUS"


class AlertSource(StrEnum):
    PROACTIVE = "PROACTIVE"
    REACTIVE = "REACTIVE"
    NETWORK = "NETWORK"
    INTEGRITY = "INTEGRITY"


class InvestigationStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    CLOSED_CLEARED = "CLOSED_CLEARED"
    CLOSED_REPORTED = "CLOSED_REPORTED"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class NetworkPattern(StrEnum):
    CIRCULAR = "CIRCULAR"
    LAYERED = "LAYERED"
    FAN_OUT = "FAN_OUT"
    FAN_IN = "FAN_IN"
    SMURFING = "SMURFING"
    PASS_THROUGH = "PASS_THROUGH"
    NORMAL = "NORMAL"


class IntegrityStatus(StrEnum):
    VERIFIED = "VERIFIED"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
    ORDER_NOT_PAYABLE = "ORDER_NOT_PAYABLE"
    CUSTOMER_MISMATCH = "CUSTOMER_MISMATCH"
    REPLAY_DETECTED = "REPLAY_DETECTED"
