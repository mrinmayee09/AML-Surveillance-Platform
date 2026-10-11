"""ORM model registry.

Importing this package registers every model on `Base.metadata`, which
`init_db()` relies on.
"""

from app.models.account import Account
from app.models.account_window_stats import AccountWindowStats
from app.models.alert import Alert
from app.models.audit_log import AuditLog
from app.models.counterparty import Counterparty
from app.models.customer import Customer
from app.models.gnn_score import GnnAccountScore
from app.models.investigation import Investigation, InvestigationNote
from app.models.network import Network, NetworkEdge, NetworkNode
from app.models.order import Order
from app.models.risk_assessment import RiskAssessment
from app.models.rule import Rule
from app.models.transaction import Transaction
from app.models.user import User

__all__ = [
    "Account",
    "AccountWindowStats",
    "Alert",
    "AuditLog",
    "Counterparty",
    "Customer",
    "GnnAccountScore",
    "Investigation",
    "InvestigationNote",
    "Network",
    "NetworkEdge",
    "NetworkNode",
    "Order",
    "RiskAssessment",
    "Rule",
    "Transaction",
    "User",
]
