"""`TransferSource` over the live database.

Only SETTLED (`COMPLETED`) transfers are graph evidence: held and blocked
attempts never moved money. Queries go through the (account, occurred_at)
indexes on `transactions`, so a window costs a handful of indexed lookups
rather than a scan of the whole table.

Amounts are converted to the schema's reference currency. Round-value and
near-threshold flags are taken on the ORIGINAL amount against the platform
(India) reporting threshold, because those signals belong to the currency and
jurisdiction the payment was made in.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List, Sequence

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.graph.builder import is_high_risk_country
from app.graph.features_v2 import (
    PLATFORM_FX_TO_REFERENCE,
    PLATFORM_REPORTING_THRESHOLD,
    STRUCTURING_BAND,
    AccountProfile,
    TransferRecord,
    is_round,
)
from app.models import Account, Customer, Transaction
from app.models.enums import TransactionStatus

# Keeps each IN (...) list comfortably inside SQLite's bound-parameter limit
_CHUNK = 400


def _chunks(items: Sequence, size: int = _CHUNK) -> Iterable[Sequence]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _near_platform_threshold(amount: float) -> bool:
    lo = PLATFORM_REPORTING_THRESHOLD * STRUCTURING_BAND[0]
    hi = PLATFORM_REPORTING_THRESHOLD * STRUCTURING_BAND[1]
    return lo <= amount <= hi


class DbTransferSource:
    """Reads transfers and account profiles through one SQLAlchemy session."""

    def __init__(self, db: Session, fx_to_reference: Dict[str, float] = PLATFORM_FX_TO_REFERENCE):
        self.db = db
        self.fx = fx_to_reference
        self._id_by_ref: Dict[str, int] = {}
        self._ref_by_id: Dict[int, str] = {}
        self._institution: Dict[int, str] = {}

    def _remember(self, rows) -> None:
        for account_id, ref, institution in rows:
            self._id_by_ref[ref] = account_id
            self._ref_by_id[account_id] = ref
            self._institution[account_id] = institution

    def _to_reference(self, amount: float, currency: str) -> float:
        rate = self.fx.get((currency or "").upper())
        if rate is None:
            raise ValueError(f"No conversion rate to the reference currency for {currency!r}")
        return float(amount) * rate

    def _ids_for(self, refs: Sequence[str]) -> List[int]:
        missing = [r for r in refs if r not in self._id_by_ref]
        for chunk in _chunks(missing):
            self._remember(
                self.db.execute(
                    select(Account.id, Account.account_ref, Account.institution).where(
                        Account.account_ref.in_(chunk)
                    )
                ).all()
            )
        return [self._id_by_ref[r] for r in refs if r in self._id_by_ref]

    def _refs_for(self, ids: Iterable[int]) -> None:
        missing = sorted({i for i in ids if i not in self._ref_by_id})
        for chunk in _chunks(missing):
            self._remember(
                self.db.execute(
                    select(Account.id, Account.account_ref, Account.institution).where(
                        Account.id.in_(chunk)
                    )
                ).all()
            )

    def fetch_touching(
        self, keys: Sequence[str], start: datetime, end: datetime
    ) -> List[TransferRecord]:
        ids = self._ids_for(list(keys))
        rows = []
        for chunk in _chunks(ids):
            rows.extend(
                self.db.execute(
                    select(
                        Transaction.id,
                        Transaction.txn_ref,
                        Transaction.sender_account_id,
                        Transaction.receiver_account_id,
                        Transaction.amount,
                        Transaction.occurred_at,
                        Transaction.channel,
                        Transaction.currency,
                        Transaction.is_international,
                    ).where(
                        Transaction.status == TransactionStatus.COMPLETED.value,
                        Transaction.occurred_at > start,
                        Transaction.occurred_at <= end,
                        or_(
                            Transaction.sender_account_id.in_(chunk),
                            Transaction.receiver_account_id.in_(chunk),
                        ),
                    )
                ).all()
            )
        self._refs_for(i for row in rows for i in (row.sender_account_id, row.receiver_account_id))

        out: Dict[str, TransferRecord] = {}
        for row in rows:
            original = float(row.amount)
            out[row.txn_ref] = TransferRecord(
                key=row.txn_ref,
                source=self._ref_by_id[row.sender_account_id],
                target=self._ref_by_id[row.receiver_account_id],
                amount=self._to_reference(original, row.currency or "INR"),
                occurred_at=row.occurred_at,
                channel=row.channel or "OTHER",
                is_international=bool(row.is_international),
                cross_institution=(
                    self._institution.get(row.sender_account_id)
                    != self._institution.get(row.receiver_account_id)
                ),
                round_amount=is_round(original),
                near_threshold=_near_platform_threshold(original),
                db_id=row.id,
            )
        return list(out.values())

    def profiles(self, keys: Sequence[str]) -> Dict[str, AccountProfile]:
        result: Dict[str, AccountProfile] = {}
        for chunk in _chunks(list(keys)):
            rows = self.db.execute(
                select(Account, Customer.pep_flag)
                .outerjoin(Customer, Account.customer_id == Customer.id)
                .where(Account.account_ref.in_(chunk))
            ).all()
            for account, pep in rows:
                self._remember([(account.id, account.account_ref, account.institution)])
                result[account.account_ref] = AccountProfile(
                    key=account.account_ref,
                    entity_type=account.entity_type,
                    is_internal=bool(account.is_internal),
                    account_age_days=int(account.opened_days_ago or 365),
                    is_dormant=bool(account.is_dormant),
                    high_risk_jurisdiction=is_high_risk_country(account.country),
                    pep=bool(pep),
                    label=account.display_name,
                    db_id=account.id,
                )
        return result

    def active_account_refs(self, start: datetime, end: datetime) -> List[str]:
        """Accounts with at least one settled transfer in (start, end]."""
        window = (
            Transaction.status == TransactionStatus.COMPLETED.value,
            Transaction.occurred_at > start,
            Transaction.occurred_at <= end,
        )
        ids = set(self.db.scalars(select(Transaction.sender_account_id).where(*window)).all())
        ids |= set(self.db.scalars(select(Transaction.receiver_account_id).where(*window)).all())
        self._refs_for(ids)
        return sorted(self._ref_by_id[i] for i in ids)
