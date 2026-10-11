"""IBM AMLworld loader (Altman et al., "Realistic Synthetic Financial
Transactions for Anti-Money Laundering Models", NeurIPS 2023 Datasets track).

Files (Kaggle: "IBM Transactions for Anti Money Laundering (AML)"):

  <VARIANT>_Trans.csv     one row per transaction, 11 columns:
      Timestamp, From Bank, Account, To Bank, Account, Amount Received,
      Receiving Currency, Amount Paid, Payment Currency, Payment Format,
      Is Laundering
  <VARIANT>_Patterns.txt  laundering attempts grouped by typology:
      BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max 16-degree Fan-Out
      <transaction rows, same 11 columns>
      END LAUNDERING ATTEMPT - FAN-OUT

Mapping onto the graph schema
-----------------------------
* account          = "<bank>:<account>" (account numbers are only unique per bank)
* amount           = Amount Paid converted to USD with rates derived from the
                     data itself (median implied rate of cross-currency rows)
* is_international = payment and receiving currency differ (the dataset has no
                     countries; a currency change is the closest proxy)
* cross_institution= From Bank != To Bank
* round_amount     = judged on Amount Paid in its own currency
* channel          = Payment Format, mapped to the shared payment rails
* timestamps       = taken as UTC (the files carry no zone)
* labels           = Is Laundering per transaction; typology from the patterns
                     file where the transaction is listed there

The laundering tail
-------------------
The simulator keeps emitting laundering for days after normal activity stops.
In HI-Small, 2022-09-01..10 carry ~5M transfers at a 0.1% laundering rate, while
2022-09-11..18 carry ~1.1K transfers of which ~59% are laundering. In those days
"is this account active at all" is a laundering detector, so any time-ordered
test split that includes them overstates every model. `load(until=...)` cuts the
data at the last day of normal activity; `summary()` reports the daily profile
and flags tail days either way.

The file is read in chunks into column arrays, so HI-Small (~5M rows) loads in
well under the memory a DataFrame of strings would need.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.graph.columnar_source import ColumnarTransferSource, TransferColumns

logger = logging.getLogger(__name__)

COLUMNS = [
    "timestamp",
    "from_bank",
    "from_account",
    "to_bank",
    "to_account",
    "amount_received",
    "receiving_currency",
    "amount_paid",
    "payment_currency",
    "payment_format",
    "is_laundering",
]
# Header as written in the files (pandas would rename the 2nd "Account")
_EXPECTED_HEADER = [
    "timestamp",
    "from bank",
    "account",
    "to bank",
    "account",
    "amount received",
    "receiving currency",
    "amount paid",
    "payment currency",
    "payment format",
    "is laundering",
]
TIMESTAMP_FORMAT = "%Y/%m/%d %H:%M"
_EPOCH = pd.Timestamp("1970-01-01", tz="UTC")
USD = "US Dollar"
# Typologies named in the AMLworld paper; anything else in a patterns file is kept as-is
UNKNOWN_TYPOLOGY = "UNLISTED"


class AmlworldFormatError(ValueError):
    """The file does not look like an AMLworld transactions/patterns file."""


@dataclass
class AmlworldDataset:
    path: Path
    source: ColumnarTransferSource
    is_laundering: np.ndarray  # bool per transfer
    typology: np.ndarray  # int16 code into `typology_names`, per transfer
    typology_names: List[str]
    fx_per_usd: Dict[str, float]  # units of currency per 1 USD
    banks: int = 0
    unmatched_pattern_rows: int = 0
    notes: List[str] = field(default_factory=list)

    @property
    def num_transfers(self) -> int:
        return len(self.source.columns)

    def daily_profile(self) -> List[Dict[str, object]]:
        """Transfers and laundering rate per UTC day."""
        days = self.source.columns.time // 86_400
        first = int(days.min())
        rows = np.bincount(days - first)
        bad = np.bincount(days - first, weights=self.is_laundering.astype(float))
        out = []
        for i, (n, b) in enumerate(zip(rows, bad)):
            if n:
                day = datetime.fromtimestamp((first + i) * 86_400, tz=timezone.utc).date()
                out.append({"day": day.isoformat(), "transfers": int(n), "laundering": int(b),
                            "laundering_rate": float(b / n)})
        return out

    def tail_days(self, min_share: float = 0.01) -> List[str]:
        """Days with under `min_share` of the median day's volume - the laundering tail."""
        profile = self.daily_profile()
        median = float(np.median([d["transfers"] for d in profile]))
        return [d["day"] for d in profile if d["transfers"] < min_share * median]

    def summary(self) -> Dict[str, object]:
        start, end = self.source.time_range
        laundering = int(self.is_laundering.sum())
        return {
            "file": self.path.name,
            "transfers": self.num_transfers,
            "accounts": len(self.source.columns.account_keys),
            "banks": self.banks,
            "laundering_transfers": laundering,
            "laundering_rate": laundering / max(self.num_transfers, 1),
            "first": start.isoformat(),
            "last": end.isoformat(),
            "currencies": sorted(self.fx_per_usd),
            "payment_formats": sorted(set(self.source.columns.channel_names)),
            "typologies": {
                name: int((self.typology == i).sum())
                for i, name in enumerate(self.typology_names)
                if name != UNKNOWN_TYPOLOGY
            },
            "laundering_without_typology": int(
                (self.is_laundering & (self.typology == self.typology_names.index(UNKNOWN_TYPOLOGY))).sum()
            ),
            "unmatched_pattern_rows": self.unmatched_pattern_rows,
            "daily": self.daily_profile(),
            "tail_days": self.tail_days(),
            "notes": self.notes,
        }


def _check_header(path: Path) -> None:
    with open(path, encoding="utf-8") as handle:
        header = [h.strip().lower() for h in handle.readline().rstrip("\n").split(",")]
    if header != _EXPECTED_HEADER:
        raise AmlworldFormatError(
            f"{path.name}: unexpected header {header!r}; expected the 11 AMLworld columns "
            f"{_EXPECTED_HEADER!r}"
        )


def _pattern_key(ts: str, fb: str, fa: str, tb: str, ta: str, paid: str, pcur: str) -> tuple:
    return (ts.strip(), fb.strip(), fa.strip(), tb.strip(), ta.strip(), round(float(paid), 2), pcur.strip())


def load_patterns(path: Path) -> Dict[tuple, List[str]]:
    """Transaction key -> typologies of the attempts that list it (in file order)."""
    lookup: Dict[tuple, List[str]] = defaultdict(list)
    current: Optional[str] = None
    with open(path, encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            if line.startswith("BEGIN LAUNDERING ATTEMPT"):
                head = line.split("-", 1)[1] if "-" in line else line
                current = head.split(":", 1)[0].strip().upper()
                continue
            if line.startswith("END LAUNDERING ATTEMPT"):
                current = None
                continue
            parts = line.split(",")
            if current is None or len(parts) != 11:
                raise AmlworldFormatError(f"{path.name}:{line_no}: unexpected line {line[:80]!r}")
            lookup[_pattern_key(*parts[:5], parts[7], parts[8])].append(current)
    return lookup


def _round_original(amount: np.ndarray) -> np.ndarray:
    out = np.zeros(amount.shape, dtype=bool)
    for unit in (100_000, 10_000, 1_000):
        out |= (amount >= unit) & (np.abs(np.mod(amount, unit)) < 1e-6)
    return out


def _derive_fx(pairs: Dict[Tuple[str, str], List[float]]) -> Dict[str, float]:
    """Units of each currency per 1 USD, from implied rates of cross-currency rows.

    `pairs[(paid, received)]` holds amount_received / amount_paid ratios. The
    median per pair is robust to the odd outlier; currencies with no direct USD
    pair are reached through others (breadth-first over the pair graph).
    """
    rate: Dict[Tuple[str, str], float] = {
        pair: float(np.median(values)) for pair, values in pairs.items() if values
    }
    per_usd: Dict[str, float] = {USD: 1.0}
    frontier = [USD]
    while frontier:
        nxt = []
        for known in frontier:
            for (paid, received), r in rate.items():
                # r = received units per paid unit
                if paid == known and received not in per_usd and r > 0:
                    per_usd[received] = per_usd[known] * r
                    nxt.append(received)
                elif received == known and paid not in per_usd and r > 0:
                    per_usd[paid] = per_usd[known] / r
                    nxt.append(paid)
        frontier = nxt
    return per_usd


def _chunks(path: Path, chunksize: int, limit: Optional[int]) -> Iterator[pd.DataFrame]:
    reader = pd.read_csv(
        path,
        header=0,
        names=COLUMNS,
        dtype={
            "from_bank": str,
            "from_account": str,
            "to_bank": str,
            "to_account": str,
            "receiving_currency": str,
            "payment_currency": str,
            "payment_format": str,
            "timestamp": str,
        },
        chunksize=chunksize,
        nrows=limit,
    )
    yield from reader


def load(
    transactions_path: Path,
    patterns_path: Optional[Path] = None,
    limit_rows: Optional[int] = None,
    chunksize: int = 500_000,
    until: Optional[date] = None,
) -> AmlworldDataset:
    """Load an AMLworld variant into a columnar source plus labels.

    `until` keeps transfers up to the end of that UTC day (see "The laundering
    tail" above). `limit_rows` reads only the first N rows - the files are not
    time-sorted, so it is only useful for tests.
    """
    path = Path(transactions_path)
    _check_header(path)
    patterns = load_patterns(Path(patterns_path)) if patterns_path else {}

    account_ids: Dict[str, int] = {}
    channel_ids: Dict[str, int] = {}
    typology_ids: Dict[str, int] = {UNKNOWN_TYPOLOGY: 0}
    banks: set = set()
    parts: Dict[str, List[np.ndarray]] = defaultdict(list)
    currency_pairs: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    matched_pattern_keys: set = set()

    def ids(values, table: Dict[str, int]) -> np.ndarray:
        return np.fromiter(
            (table.setdefault(v, len(table)) for v in values), dtype=np.int32, count=len(values)
        )

    for chunk in _chunks(path, chunksize, limit_rows):
        times = pd.to_datetime(chunk["timestamp"], format=TIMESTAMP_FORMAT, utc=True)
        src_keys = (chunk["from_bank"] + ":" + chunk["from_account"]).tolist()
        dst_keys = (chunk["to_bank"] + ":" + chunk["to_account"]).tolist()
        banks.update(chunk["from_bank"].unique())
        banks.update(chunk["to_bank"].unique())

        paid = chunk["amount_paid"].to_numpy(dtype=np.float64)
        received = chunk["amount_received"].to_numpy(dtype=np.float64)
        pay_cur = chunk["payment_currency"].to_numpy()
        rec_cur = chunk["receiving_currency"].to_numpy()
        launder = chunk["is_laundering"].to_numpy().astype(bool)

        cross = pay_cur != rec_cur
        for p, r, a_paid, a_rec in zip(pay_cur[cross], rec_cur[cross], paid[cross], received[cross]):
            if a_paid > 0 and a_rec > 0:
                currency_pairs[(p, r)].append(a_rec / a_paid)

        typ = np.zeros(len(chunk), dtype=np.int16)
        if patterns:
            rows = chunk.iloc[np.flatnonzero(launder)]
            for pos, row in zip(np.flatnonzero(launder), rows.itertuples(index=False)):
                key = _pattern_key(
                    row.timestamp, row.from_bank, row.from_account, row.to_bank,
                    row.to_account, str(row.amount_paid), row.payment_currency,
                )
                names = patterns.get(key)
                if names:
                    typ[pos] = typology_ids.setdefault(names[0], len(typology_ids))
                    matched_pattern_keys.add(key)

        parts["source"].append(ids(src_keys, account_ids))
        parts["target"].append(ids(dst_keys, account_ids))
        parts["paid"].append(paid)
        parts["pay_cur"].append(pay_cur.astype(str))
        parts["time"].append(((times - _EPOCH) // pd.Timedelta(seconds=1)).to_numpy(np.int64))
        parts["channel"].append(ids(chunk["payment_format"].tolist(), channel_ids).astype(np.int16))
        parts["intl"].append(cross)
        parts["cross_inst"].append((chunk["from_bank"] != chunk["to_bank"]).to_numpy())
        parts["launder"].append(launder)
        parts["typology"].append(typ)
        logger.info("AMLworld: read %s rows", sum(len(p) for p in parts["source"]))

    if not parts:
        raise AmlworldFormatError(f"{path.name}: no transactions")

    fx = _derive_fx(currency_pairs)
    pay_cur_all = np.concatenate(parts["pay_cur"])
    paid_all = np.concatenate(parts["paid"])
    notes: List[str] = []
    missing = sorted(set(np.unique(pay_cur_all)) - set(fx))
    if missing:
        notes.append(f"no USD rate derivable for {missing}; their transfers were dropped")
    keep = np.isin(pay_cur_all, list(fx))
    if until is not None:
        cutoff = datetime.combine(until + timedelta(days=1), time(0), tzinfo=timezone.utc).timestamp()
        late = np.concatenate(parts["time"]) >= cutoff
        launder_all = np.concatenate(parts["launder"])
        notes.append(
            f"kept transfers up to {until.isoformat()} (UTC); dropped {int(late.sum())} later "
            f"transfers, {int((late & launder_all).sum())} of them laundering"
        )
        keep &= ~late
    divisor = pd.Series(pay_cur_all).map(fx).to_numpy(dtype=np.float64, na_value=math.nan)

    def cat(name: str) -> np.ndarray:
        return np.concatenate(parts[name])[keep]

    columns = TransferColumns(
        account_keys=[None] * len(account_ids),  # type: ignore[list-item]
        source=cat("source"),
        target=cat("target"),
        amount=(paid_all / divisor)[keep],
        time=cat("time").astype(np.int64),
        channel=cat("channel"),
        channel_names=[None] * len(channel_ids),  # type: ignore[list-item]
        is_international=cat("intl"),
        cross_institution=cat("cross_inst"),
        round_amount=_round_original(paid_all)[keep],
    )
    for key, i in account_ids.items():
        columns.account_keys[i] = key
    for name, i in channel_ids.items():
        columns.channel_names[i] = name

    typology_names = [None] * len(typology_ids)
    for name, i in typology_ids.items():
        typology_names[i] = name

    total_pattern_rows = sum(len(v) for v in patterns.values())
    unmatched = len(patterns) - len(matched_pattern_keys) if patterns else 0
    if patterns and unmatched and limit_rows is None:
        notes.append(f"{unmatched} of {len(patterns)} pattern rows matched no laundering transaction")

    dataset = AmlworldDataset(
        path=path,
        source=ColumnarTransferSource(columns),
        is_laundering=cat("launder"),
        typology=cat("typology"),
        typology_names=typology_names,  # type: ignore[arg-type]
        fx_per_usd=fx,
        banks=len(banks),
        unmatched_pattern_rows=unmatched,
        notes=notes,
    )
    logger.info(
        "AMLworld loaded: %s transfers, %s accounts, %s laundering, %s pattern rows",
        dataset.num_transfers, len(columns.account_keys), int(dataset.is_laundering.sum()),
        total_pattern_rows,
    )
    return dataset
