"""Evaluation metrics for sampled AML data.

Negatives are subsampled when windows are built and carry weight 1/rate, so
every metric here takes sample weights: weighted precision, PR-AUC and alert
rate estimate what the model would do on ALL active accounts, at the real
(heavily imbalanced) class balance. Recall needs no weights when every positive
is kept, but takes them anyway so a capped positive set stays unbiased.

The decision threshold is always chosen on the validation split (maximum
weighted F1) and then applied unchanged to the test split.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import numpy as np
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score


def best_threshold(y: np.ndarray, score: np.ndarray, weight: np.ndarray) -> float:
    """Score threshold that maximises weighted F1."""
    if y.sum() == 0:
        return 0.5
    precision, recall, thresholds = precision_recall_curve(y, score, sample_weight=weight)
    f1 = 2 * precision * recall / np.clip(precision + recall, 1e-12, None)
    best = int(np.nanargmax(f1[:-1])) if thresholds.size else 0
    return float(thresholds[best]) if thresholds.size else 0.5


def evaluate(
    y: np.ndarray,
    score: np.ndarray,
    weight: np.ndarray,
    threshold: float,
    typology: Optional[np.ndarray] = None,
    typology_names: Optional[Sequence[str]] = None,
) -> Dict[str, object]:
    y = y.astype(int)
    pred = score >= threshold
    pos, neg = y == 1, y == 0
    tp = float(weight[pos & pred].sum())
    fp = float(weight[neg & pred].sum())
    fn = float(weight[pos & ~pred].sum())
    precision = tp / (tp + fp) if tp + fp > 0 else 0.0
    recall = tp / (tp + fn) if tp + fn > 0 else 0.0
    both = len(np.unique(y)) == 2
    out: Dict[str, object] = {
        "pr_auc": float(average_precision_score(y, score, sample_weight=weight)) if both else None,
        "roc_auc": float(roc_auc_score(y, score, sample_weight=weight)) if both else None,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall > 0 else 0.0,
        "threshold": float(threshold),
        # Share of all active accounts that would be flagged (the analyst workload)
        "alert_rate": float(weight[pred].sum() / weight.sum()) if weight.sum() > 0 else 0.0,
        # Estimated positive rate among all active accounts (for context)
        "base_rate": float(weight[pos].sum() / weight.sum()) if weight.sum() > 0 else 0.0,
        "windows": int(y.size),
        "positives": int(pos.sum()),
    }
    if typology is not None and typology_names is not None:
        per: Dict[str, Dict[str, float]] = {}
        for code, name in enumerate(typology_names):
            mask = pos & (typology == code)
            if code == 0 or not mask.any():
                continue
            per[name] = {"recall": float(pred[mask].mean()), "support": int(mask.sum())}
        out["recall_by_typology"] = per
    return out


def summarise(runs: List[Dict[str, object]]) -> Dict[str, object]:
    """Mean and standard deviation of each numeric metric across seeds."""
    keys = [k for k, v in runs[0].items() if isinstance(v, (int, float)) and v is not None]
    summary: Dict[str, object] = {"runs": len(runs)}
    for key in keys:
        values = np.asarray([r[key] for r in runs if r.get(key) is not None], dtype=float)
        if values.size:
            summary[key] = {"mean": float(values.mean()), "std": float(values.std(ddof=0))}
    if "recall_by_typology" in runs[0]:
        names = sorted({n for r in runs for n in r.get("recall_by_typology", {})})
        summary["recall_by_typology"] = {
            n: {
                "mean": float(np.mean([r["recall_by_typology"][n]["recall"] for r in runs if n in r["recall_by_typology"]])),
                "support": int(max(r["recall_by_typology"][n]["support"] for r in runs if n in r["recall_by_typology"])),
            }
            for n in names
        }
    return summary
