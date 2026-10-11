"""R5: scoring live accounts with the trained window GNN.

The model is trained offline (R2/R3) on IBM AMLworld and exported to
`app/gnn/artifacts/aml_gnn_v2.pt`. Here the app only LOADS it and scores:

    settled transfer / "Run GNN scoring"
        -> 7-day neighbourhood window per account (same builder as training)
        -> GraphSAGE score + occlusion explanation (top transfers)
        -> stored in gnn_account_scores; above the threshold -> one alert

The threshold is the one chosen on AMLworld's validation split and travels in
the checkpoint. Accuracy figures come from AMLworld; on the platform's INR / UPI
demo data the scores illustrate the mechanism, which the evidence says plainly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Dict, List, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.types import as_utc
from app.gnn.explain_v2 import explain
from app.gnn.v2_model import EXPORT_PATH, LoadedModel, load_checkpoint
from app.graph.db_source import DbTransferSource
from app.graph.window import WindowCache, build_window
from app.models import Account, GnnAccountScore, Transaction
from app.models.enums import AlertSource, TransactionStatus
from app.services import alert_service

logger = logging.getLogger(__name__)

ALERT_TYPE = "GNN_ACCOUNT_RISK"
DOMAIN_NOTE = (
    "Scored by a GraphSAGE model trained and evaluated on IBM AMLworld (a public "
    "simulated benchmark). On this platform's data the score illustrates how the "
    "network layer works; its measured accuracy is the AMLworld result."
)
MAX_ACCOUNTS_PER_RUN = 500
# Transfers whose removal moves the score by less than this are not shown as reasons
MIN_SCORE_DROP = 0.005


@lru_cache(maxsize=1)
def get_model() -> Optional[LoadedModel]:
    """The exported model, or None when it has not been trained / torch is absent."""
    if not EXPORT_PATH.exists():
        return None
    try:
        return load_checkpoint(EXPORT_PATH)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("could not load the window GNN from %s: %s", EXPORT_PATH, exc)
        return None


def status() -> Dict[str, object]:
    loaded = get_model()
    if loaded is None:
        return {"available": False, "path": str(EXPORT_PATH),
                "message": "Not trained yet: run python -m app.gnn.r3 (see README)."}
    test = loaded.metrics.get("test", {})
    return {
        "available": True,
        "name": loaded.name,
        "variant": loaded.variant,
        "threshold": loaded.threshold,
        "training_data": loaded.training_data,
        "window": {"days": loaded.window.days, "hops": loaded.window.hops},
        "test_metrics": {k: test.get(k) for k in ("pr_auc", "precision", "recall", "f1", "base_rate")},
        "note": DOMAIN_NOTE,
    }


def latest_settlement(db: Session) -> Optional[datetime]:
    value = db.scalar(
        select(func.max(Transaction.occurred_at)).where(
            Transaction.status == TransactionStatus.COMPLETED.value
        )
    )
    return as_utc(value) if value else None


def score_accounts(
    db: Session,
    account_refs: Sequence[str],
    window_end: Optional[datetime] = None,
    raise_alerts: bool = True,
) -> List[GnnAccountScore]:
    """Score each account's neighbourhood window; persist; alert above threshold."""
    loaded = get_model()
    if loaded is None or not account_refs:
        return []
    end = as_utc(window_end) if window_end else latest_settlement(db)
    if end is None:
        return []

    source = DbTransferSource(db)
    cache = WindowCache()
    accounts = {
        a.account_ref: a
        for a in db.scalars(select(Account).where(Account.account_ref.in_(list(account_refs))))
    }
    rows: List[GnnAccountScore] = []
    for ref in sorted(set(account_refs))[:MAX_ACCOUNTS_PER_RUN]:
        account = accounts.get(ref)
        if account is None:
            continue
        window = build_window(source, ref, end, loaded.window, loaded.schema, cache)
        result = explain(loaded.model, window.node_features, window.edge_index, window.edge_features)
        top = _describe(db, window, result["top"])
        row = GnnAccountScore(
            account_id=account.id,
            window_end=end,
            score=round(result["score"], 6),
            threshold=loaded.threshold,
            flagged=result["score"] >= loaded.threshold,
            window_nodes=window.num_nodes,
            window_edges=window.num_edges,
            model_name=loaded.name,
            model_variant=loaded.variant,
            top_transfers=top,
        )
        db.add(row)
        if row.flagged and raise_alerts:
            alert, _ = _raise_alert(db, account, row, loaded)
            if alert is not None:
                db.flush()
                row.alert_id = alert.id
        rows.append(row)
    db.flush()
    return rows


def score_recent(db: Session, hours: int = 24, window_end: Optional[datetime] = None) -> Dict[str, object]:
    """Score every account with a settled transfer in the `hours` before `window_end`.

    `window_end` defaults to the latest settled transfer, not the wall clock, so
    seeded demo data that is a few days old still has activity to score.
    """
    end = as_utc(window_end) if window_end else latest_settlement(db)
    if end is None or get_model() is None:
        return {"scored": 0, "flagged": 0, "window_end": None, "accounts": []}
    refs = DbTransferSource(db).active_account_refs(end - timedelta(hours=hours), end)
    rows = score_accounts(db, refs, end)
    flagged = sorted((r for r in rows if r.flagged), key=lambda r: -r.score)
    return {
        "scored": len(rows),
        "flagged": len(flagged),
        "window_end": end.isoformat(),
        "accounts": [
            {"account_ref": r.account.account_ref, "score": r.score, "alert_id": r.alert_id}
            for r in flagged[:25]
        ],
        "truncated": len(refs) > MAX_ACCOUNTS_PER_RUN,
    }


def latest_for(db: Session, account_ref: str) -> Optional[GnnAccountScore]:
    return db.scalar(
        select(GnnAccountScore)
        .join(Account, Account.id == GnnAccountScore.account_id)
        .where(Account.account_ref == account_ref)
        .order_by(GnnAccountScore.window_end.desc(), GnnAccountScore.id.desc())
        .limit(1)
    )


def to_dict(row: GnnAccountScore) -> Dict[str, object]:
    return {
        "account_ref": row.account.account_ref,
        "score": row.score,
        "threshold": row.threshold,
        "flagged": row.flagged,
        "window_end": row.window_end,
        "window_nodes": row.window_nodes,
        "window_edges": row.window_edges,
        "model": f"{row.model_name} ({row.model_variant})",
        "top_transfers": row.top_transfers or [],
        "note": DOMAIN_NOTE,
    }


# ---------------------------------------------------------------------------


def _describe(db: Session, window, attributions) -> List[Dict[str, object]]:
    """Explanation edges -> transfers an analyst can look up (original amount)."""
    attributions = [a for a in attributions if a.score_drop >= MIN_SCORE_DROP]
    if not attributions:
        return []
    refs = [window.transfers[a.edge].key for a in attributions]
    originals = {
        t.txn_ref: t for t in db.scalars(select(Transaction).where(Transaction.txn_ref.in_(refs)))
    }
    out = []
    for a in attributions:
        t = window.transfers[a.edge]
        txn = originals.get(t.key)
        out.append({
            "rank": a.rank,
            "txn_ref": t.key,
            "sender": t.source,
            "receiver": t.target,
            "amount": round(txn.amount, 2) if txn else round(t.amount, 2),
            "currency": txn.currency if txn else "USD",
            "occurred_at": t.occurred_at.isoformat(),
            "score_drop": round(a.score_drop, 4),
        })
    return out


def _raise_alert(db: Session, account: Account, row: GnnAccountScore, loaded: LoadedModel):
    top = row.top_transfers or []
    lines = "; ".join(
        f"{t['txn_ref']} {t['sender']} -> {t['receiver']} {t['currency']} {t['amount']:,.2f} "
        f"(score -{t['score_drop'] * 100:.1f} pts without it)"
        for t in top[:5]
    )
    first = db.scalar(select(Transaction.id).where(Transaction.txn_ref == top[0]["txn_ref"])) if top else None
    return alert_service.upsert_alert(
        db,
        # One live alert per account per day of activity
        dedupe_key=alert_service.dedupe_key_for(
            "GNN", account.id, ALERT_TYPE, [row.window_end.date().isoformat()]
        ),
        suppress_after_close=timedelta(days=7),
        source=AlertSource.NETWORK.value,
        alert_type=ALERT_TYPE,
        title=f"Graph model flags account {account.account_ref} - neighbourhood requires investigation",
        explanation=(
            f"The GraphSAGE network model scored account {account.account_ref} at "
            f"{row.score:.2f} against a threshold of {row.threshold:.2f}, from its 7-day "
            f"neighbourhood of {row.window_nodes} accounts and {row.window_edges} transfers. "
            f"The score rests mainly on: {lines or 'no single transfer'}. "
            "These are model-generated risk indicators that require investigation; they "
            "do not establish that any offence occurred. " + DOMAIN_NOTE
        ),
        risk_score=round(row.score * 100, 1),
        risk_level=_level(row.score, row.threshold),
        customer_id=account.customer_id,
        account_id=account.id,
        transaction_id=first,
        rule_code="NETWORK_GNN",
        evidence={
            "headline": f"GNN score {row.score:.2f} (threshold {row.threshold:.2f}) - "
                        f"top {len(top[:5])} transfers behind it below",
            "metrics": [
                {"label": f"#{t['rank']} {t['txn_ref']}",
                 "value": f"{t['currency']} {t['amount']:,.2f}, -{t['score_drop'] * 100:.1f} pts"}
                for t in top[:5]
            ],
            "transaction_refs": [t["txn_ref"] for t in top],
            "layer": "NETWORK (window GraphSAGE)",
            "model": f"{loaded.name} ({loaded.variant})",
            "pattern_code": ALERT_TYPE,
        },
        raised_at=row.window_end,
    )


def _level(score: float, threshold: float) -> str:
    if score >= max(0.9, threshold):
        return "CRITICAL"
    if score >= threshold:
        return "HIGH"
    return "MEDIUM"
