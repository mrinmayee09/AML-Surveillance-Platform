"""`TransferSource` over column arrays - for datasets too big for Python objects.

IBM AMLworld HI-Small is ~5M transfers. As Python objects that is several GB;
as columns it is ~0.2 GB. Transfers are stored as NumPy arrays plus, per account,
its transfer indices sorted by time, so "every transfer touching this account in
(start, end]" is two binary searches. `TransferRecord` objects are materialised
only for the transfers a window actually asks for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

import numpy as np

from app.graph.features_v2 import AccountProfile, TransferRecord


@dataclass
class TransferColumns:
    """Column arrays, one entry per transfer. Amounts in the reference currency."""

    account_keys: List[str]  # account id -> key
    source: np.ndarray  # int32 account ids
    target: np.ndarray  # int32 account ids
    amount: np.ndarray  # float64
    time: np.ndarray  # int64 epoch seconds (UTC)
    channel: np.ndarray  # int16 code into `channel_names`
    channel_names: List[str]
    is_international: np.ndarray  # bool
    cross_institution: np.ndarray  # bool
    round_amount: Optional[np.ndarray] = None  # bool, judged on the original amount

    def __len__(self) -> int:
        return int(self.source.shape[0])


def _utc(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


class ColumnarTransferSource:
    """Fast window queries over `TransferColumns`."""

    def __init__(self, columns: TransferColumns):
        self.columns = columns
        self._index = {key: i for i, key in enumerate(columns.account_keys)}
        n = len(columns)
        n_accounts = len(columns.account_keys)

        # Per-account incidence lists sorted by time (CSR layout). A self
        # transfer is listed once.
        txn = np.arange(n, dtype=np.int64)
        not_self = columns.source != columns.target
        owner = np.concatenate([columns.source, columns.target[not_self]])
        incident = np.concatenate([txn, txn[not_self]])
        order = np.lexsort((columns.time[incident], owner))
        self._incident = incident[order]
        self._incident_time = columns.time[self._incident]
        counts = np.bincount(owner, minlength=n_accounts)
        self._indptr = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)

        # Global time order, for "everything that happened in this interval"
        self._by_time = np.argsort(columns.time, kind="stable")
        self._sorted_time = columns.time[self._by_time]

    # -- TransferSource ------------------------------------------------------

    def fetch_touching(
        self, keys: Sequence[str], start: datetime, end: datetime
    ) -> List[TransferRecord]:
        lo_t, hi_t = start.timestamp(), end.timestamp()
        picked: List[np.ndarray] = []
        for key in keys:
            account = self._index.get(key)
            if account is None:
                continue
            a, b = self._indptr[account], self._indptr[account + 1]
            times = self._incident_time[a:b]
            # half-open (start, end]
            left = a + np.searchsorted(times, lo_t, side="right")
            right = a + np.searchsorted(times, hi_t, side="right")
            if right > left:
                picked.append(self._incident[left:right])
        if not picked:
            return []
        return [self.record(int(i)) for i in np.unique(np.concatenate(picked))]

    def profiles(self, keys: Sequence[str]) -> Dict[str, AccountProfile]:
        return {}  # transaction-only dataset: no KYC profiles

    # -- dataset helpers -----------------------------------------------------

    def record(self, i: int) -> TransferRecord:
        c = self.columns
        return TransferRecord(
            key=f"T{i}",
            source=c.account_keys[c.source[i]],
            target=c.account_keys[c.target[i]],
            amount=float(c.amount[i]),
            occurred_at=_utc(int(c.time[i])),
            channel=c.channel_names[c.channel[i]],
            is_international=bool(c.is_international[i]),
            cross_institution=bool(c.cross_institution[i]),
            round_amount=bool(c.round_amount[i]) if c.round_amount is not None else None,
            db_id=i,
        )

    def transfers_between(self, start: datetime, end: datetime) -> np.ndarray:
        """Indices of transfers in (start, end], in time order."""
        left = np.searchsorted(self._sorted_time, start.timestamp(), side="right")
        right = np.searchsorted(self._sorted_time, end.timestamp(), side="right")
        return self._by_time[left:right]

    def account_key(self, account_id: int) -> str:
        return self.columns.account_keys[account_id]

    @property
    def time_range(self) -> tuple[datetime, datetime]:
        return _utc(int(self._sorted_time[0])), _utc(int(self._sorted_time[-1]))
