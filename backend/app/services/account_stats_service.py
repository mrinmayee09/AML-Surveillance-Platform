"""The account stats store: per-account window statistics, materialised.

`refresh` recomputes accounts through the same pure functions the window
builder and the trainer use (`app.graph.features_v2`), so a stored row is
exactly what a fresh window would compute for that account at that time.

The live pipeline calls `refresh` with the accounts a settled transfer touched;
the seed and the hourly reconciliation call it with no accounts, which means
"every account active in the window". Readers use `load_fresh`, which drops
rows that are outdated (old schema, too old, or missing a newer transfer).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.types import as_utc, utcnow
from app.graph.db_source import DbTransferSource
from app.graph.features_v2 import (
    FEATURE_SCHEMA_VERSION,
    AccountProfile,
    AccountWindowStats as WindowStats,
    WindowConfig,
    account_feature_vector,
    compute_account_stats,
)
from app.models import Account, AccountWindowStats, Transaction
from app.models.enums import TransactionStatus


def compute(
    db: Session,
    account_refs: Sequence[str],
    window_end: Optional[datetime] = None,
    days: int = WindowConfig().days,
) -> Dict[str, Tuple[AccountProfile, WindowStats]]:
    """Profile + window stats for each account, straight from `transactions`."""
    end = as_utc(window_end) if window_end else utcnow()
    start = end - timedelta(days=days)
    source = DbTransferSource(db)
    refs = sorted(set(account_refs))

    touching: Dict[str, list] = {ref: [] for ref in refs}
    for t in source.fetch_touching(refs, start, end):
        if t.source in touching:
            touching[t.source].append(t)
        if t.target in touching and t.target != t.source:
            touching[t.target].append(t)

    profiles = source.profiles(refs)
    return {
        ref: (
            profiles.get(ref) or AccountProfile(key=ref),
            compute_account_stats(ref, touching[ref], start, end),
        )
        for ref in refs
    }


def refresh(
    db: Session,
    account_refs: Optional[Sequence[str]] = None,
    window_end: Optional[datetime] = None,
    days: int = WindowConfig().days,
) -> int:
    """Recompute and upsert store rows. Returns the number of accounts written.

    `account_refs=None` refreshes every account with settled activity in the
    window. Accounts that have gone quiet keep their last row, which
    `load_fresh` will then reject as too old.
    """
    end = as_utc(window_end) if window_end else utcnow()
    if account_refs is None:
        account_refs = DbTransferSource(db).active_account_refs(end - timedelta(days=days), end)
    computed = compute(db, account_refs, end, days)
    if not computed:
        return 0

    ids = dict(
        db.execute(
            select(Account.account_ref, Account.id).where(Account.account_ref.in_(list(computed)))
        ).all()
    )
    existing = {
        row.account_id: row
        for row in db.scalars(
            select(AccountWindowStats).where(
                AccountWindowStats.account_id.in_(list(ids.values())),
                AccountWindowStats.window_days == days,
            )
        ).all()
    }

    written = 0
    for ref, (profile, stats) in computed.items():
        account_id = ids.get(ref)
        if account_id is None:
            continue
        row = existing.get(account_id)
        if row is None:
            row = AccountWindowStats(account_id=account_id, window_days=days)
            db.add(row)
        row.schema_version = FEATURE_SCHEMA_VERSION
        row.window_start = stats.window_start
        row.window_end = stats.window_end
        row.last_activity_at = stats.last_activity_at
        row.stats = stats.to_dict()
        row.features = [round(v, 6) for v in account_feature_vector(profile, stats)]
        written += 1
    db.flush()
    return written


def load_fresh(
    db: Session,
    account_refs: Sequence[str],
    days: int = WindowConfig().days,
    max_age: timedelta = timedelta(hours=1),
    now: Optional[datetime] = None,
) -> Dict[str, AccountWindowStats]:
    """Stored rows that can still be trusted, keyed by account ref.

    A row is dropped when it was computed under another feature schema, its
    window ended more than `max_age` ago, or a settled transfer touching the
    account happened after its window ended.
    """
    now = as_utc(now) if now else utcnow()
    rows = db.execute(
        select(Account.account_ref, AccountWindowStats)
        .join(AccountWindowStats, AccountWindowStats.account_id == Account.id)
        .where(
            Account.account_ref.in_(list(account_refs)),
            AccountWindowStats.window_days == days,
            AccountWindowStats.schema_version == FEATURE_SCHEMA_VERSION,
        )
    ).all()
    candidates = {
        ref: row for ref, row in rows if row.window_end and now - row.window_end <= max_age
    }
    if not candidates:
        return {}

    since = min(row.window_end for row in candidates.values())
    latest: Dict[int, datetime] = {}
    for column in (Transaction.sender_account_id, Transaction.receiver_account_id):
        for account_id, newest in db.execute(
            select(column, func.max(Transaction.occurred_at))
            .where(
                column.in_([row.account_id for row in candidates.values()]),
                Transaction.status == TransactionStatus.COMPLETED.value,
                Transaction.occurred_at > since,
            )
            .group_by(column)
        ).all():
            newest = as_utc(newest)
            if account_id not in latest or newest > latest[account_id]:
                latest[account_id] = newest

    return {
        ref: row
        for ref, row in candidates.items()
        if row.account_id not in latest or latest[row.account_id] <= row.window_end
    }
