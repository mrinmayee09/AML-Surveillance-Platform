"""A small file in the exact IBM AMLworld format, for tests and smoke runs.

It only exercises the pipeline (parsing, conversion, labels, splits, windows,
training loop). It is NOT training data and no result on it means anything.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

HEADER = (
    "Timestamp,From Bank,Account,To Bank,Account,Amount Received,Receiving Currency,"
    "Amount Paid,Payment Currency,Payment Format,Is Laundering"
)
FORMATS = ["ACH", "Wire", "Cheque", "Credit Card", "Cash"]
EUR_PER_USD = 0.9


def _row(ts, fb, fa, tb, ta, received, rcur, paid, pcur, fmt, launder) -> str:
    return (
        f"{ts:%Y/%m/%d %H:%M},{fb},{fa},{tb},{ta},{received:.2f},{rcur},"
        f"{paid:.2f},{pcur},{fmt},{launder}"
    )


def write_fixture(folder: Path, days: int = 12, seed: int = 3) -> Tuple[Path, Path, Dict]:
    rng = random.Random(seed)
    banks = ["001", "002", "003"]
    accounts = [(b, f"80{b}{i:05X}") for b in banks for i in range(20)]
    start = datetime(2022, 9, 1, 0, 0)
    rows: List[Tuple[datetime, str]] = []
    patterns: List[str] = []
    truth = {"laundering": 0, "FAN-OUT": 0, "CYCLE": 0, "euro_cross": 0}

    for day in range(days):
        base = start + timedelta(days=day)
        for _ in range(50):
            (fb, fa), (tb, ta) = rng.sample(accounts, 2)
            ts = base + timedelta(minutes=rng.randrange(1, 1439))
            paid = round(rng.uniform(50, 5000), 2)
            if rng.random() < 0.1:
                rows.append((ts, _row(ts, fb, fa, tb, ta, paid * EUR_PER_USD, "Euro", paid, "US Dollar", "Wire", 0)))
                truth["euro_cross"] += 1
            else:
                rows.append((ts, _row(ts, fb, fa, tb, ta, paid, "US Dollar", paid, "US Dollar", rng.choice(FORMATS), 0)))

        # One fan-out a day: a source spreads value over four mules within the hour
        src = accounts[(day * 7) % len(accounts)]
        mules = rng.sample([a for a in accounts if a != src], 4)
        block = []
        t0 = base + timedelta(hours=10, minutes=rng.randrange(0, 50))
        for k, (mb, ma) in enumerate(mules):
            ts = t0 + timedelta(minutes=k * 3)
            amount = round(rng.uniform(8000, 9500), 2)
            line = _row(ts, src[0], src[1], mb, ma, amount, "US Dollar", amount, "US Dollar", "ACH", 1)
            rows.append((ts, line))
            block.append(line)
        patterns += ["BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max 4-degree Fan-Out", *block, "END LAUNDERING ATTEMPT - FAN-OUT", ""]
        truth["FAN-OUT"] += 4

        # Every third day a four-account cycle
        if day % 3 == 0:
            ring = rng.sample(accounts, 4)
            block = []
            t0 = base + timedelta(hours=15)
            for k in range(4):
                (fb, fa), (tb, ta) = ring[k], ring[(k + 1) % 4]
                ts = t0 + timedelta(minutes=20 * k)
                amount = 20000 - 300 * k
                line = _row(ts, fb, fa, tb, ta, amount, "US Dollar", amount, "US Dollar", "Wire", 1)
                rows.append((ts, line))
                block.append(line)
            patterns += ["BEGIN LAUNDERING ATTEMPT - CYCLE:  Max 4 hops", *block, "END LAUNDERING ATTEMPT - CYCLE", ""]
            truth["CYCLE"] += 4

    rows.sort(key=lambda r: r[0])
    truth["laundering"] = truth["FAN-OUT"] + truth["CYCLE"]
    truth["rows"] = len(rows)
    folder.mkdir(parents=True, exist_ok=True)
    trans = folder / "FIX_Trans.csv"
    trans.write_text("\n".join([HEADER] + [r for _, r in rows]) + "\n", encoding="utf-8")
    pats = folder / "FIX_Patterns.txt"
    pats.write_text("\n".join(patterns), encoding="utf-8")
    return trans, pats, truth
