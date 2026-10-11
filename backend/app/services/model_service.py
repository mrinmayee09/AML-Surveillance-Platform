"""Model Insights: honest reporting of what each model is and is not.

This module is deliberately conservative. It reads metrics from the actual
artifacts rather than any hard-coded table, and when no trained artifact is
loaded it says so instead of showing plausible-looking numbers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.gnn.registry import get_gnn_engine
from app.graph.types import (
    EDGE_FEATURE_SPEC,
    NODE_FEATURE_SPEC,
)
from app.ml.features import FEATURE_BY_NAME, FEATURE_SPEC
from app.ml.model import RandomForestRiskModel
from app.ml.registry import get_proactive_model
from app.models import Account, Network, Transaction
from app.schemas.common import ModelProvenance

HONESTY_STATEMENT = (
    "This page reports what each model actually is. Metrics are read from the "
    "trained artifacts, not hard-coded. Both models are fitted on SYNTHETIC data "
    "because a prototype has no access to confirmed SAR/STR outcomes, so their "
    "scores measure recognition of synthetic patterns - not real-world laundering "
    "detection performance. Where no trained artifact is loaded, the platform "
    "reports the active component as untrained rather than showing placeholder "
    "figures. No output from either model constitutes evidence of criminal activity."
)


def _provenance(
    name: str, version: str, model_type: str, trained: bool, training_data: str, notes: str
) -> ModelProvenance:
    return ModelProvenance(
        model_name=name,
        model_version=version,
        model_type=model_type,
        trained=trained,
        training_data=training_data,
        notes=notes,
    )


def proactive_card() -> Dict[str, Any]:
    model = get_proactive_model()
    importances = model.feature_importances()

    features: List[Dict[str, Any]] = []
    for spec in FEATURE_SPEC:
        features.append(
            {
                "feature": spec.name,
                "label": spec.label,
                "importance": round(importances.get(spec.name, 0.0), 5),
                "description": spec.description,
            }
        )
    features.sort(key=lambda f: f["importance"], reverse=True)

    metrics: Optional[Dict[str, Any]] = None
    hyperparameters: Dict[str, Any] = {}
    training_rows = 0
    class_balance: Dict[str, int] = {}
    caveats: List[str] = []

    if isinstance(model, RandomForestRiskModel):
        raw = model.metrics or {}
        if raw:
            metrics = {
                "accuracy": raw.get("accuracy", 0.0),
                "precision": raw.get("precision", 0.0),
                "recall": raw.get("recall", 0.0),
                "f1": raw.get("f1", 0.0),
                "roc_auc": raw.get("roc_auc"),
                "support": raw.get("support", 0),
                "confusion_matrix": raw.get("confusion_matrix", [[0, 0], [0, 0]]),
                "labels": raw.get("labels", ["Normal", "Elevated risk"]),
            }
        hyperparameters = model.hyperparameters
        training_rows = model.training_rows
        class_balance = model.class_balance
        from app.ml.trainer import train  # noqa: F401  (docstring reference)

        # Caveats travel with the artifact; fall back to the module-level list
        try:
            import joblib

            from app.core.config import settings

            artifact = joblib.load(settings.ml_model_abspath)
            caveats = artifact.get("caveats", [])
        except Exception:  # pragma: no cover
            caveats = []
    else:
        caveats = [
            "NO TRAINED ARTIFACT IS LOADED. The active scorer is a transparent "
            "weighted heuristic with hand-set weights and no fitting. Run "
            "`python -m seed.seed` to train the RandomForest model.",
            "Because nothing was fitted, no accuracy, precision, recall or confusion "
            "matrix can honestly be reported, and none is shown.",
        ]

    return {
        "provenance": _provenance(
            model.name,
            model.version,
            model.model_type,
            model.trained,
            model.training_data,
            model.notes,
        ),
        "purpose": (
            "Behavioural risk classification. Estimates the probability that a "
            "customer's transaction behaviour is drifting toward an elevated-risk "
            "profile, BEFORE a transaction is authorised."
        ),
        "algorithm": model.model_type,
        "hyperparameters": hyperparameters,
        "feature_count": len(FEATURE_SPEC),
        "features": features,
        "metrics": metrics,
        "trained_at": model.trained_at,
        "training_rows": training_rows,
        "class_balance": class_balance,
        "caveats": caveats,
    }


def gnn_card(db: Session) -> Dict[str, Any]:
    engine = get_gnn_engine()
    metrics = engine.metrics or None

    account_count = int(db.scalar(select(func.count(Account.id))) or 0)
    txn_count = int(db.scalar(select(func.count(Transaction.id))) or 0)
    active = Network.is_active.is_(True)
    network_count = int(db.scalar(select(func.count(Network.id)).where(active)) or 0)
    suspicious_count = int(
        db.scalar(
            select(func.count(Network.id)).where(active, Network.is_suspicious.is_(True))
        )
        or 0
    )

    caveats = getattr(engine, "caveats", None) or []
    if not engine.trained:
        caveats = [
            "NO TRAINED GNN IS LOADED. The active component is an analytic graph "
            "engine: real centrality and structural analysis, but with hand-set "
            "weights and no learned parameters. It is not a neural network.",
            "No node, edge or subgraph metrics are reported, because nothing was "
            "trained and any figure shown would be fabricated.",
            "Run `python -m seed.seed` (with PyTorch installed) to train the GNN.",
        ]

    hyperparameters = getattr(engine, "hyperparameters", {}) or {}
    dataset_summary = getattr(engine, "dataset_summary", {}) or {}

    return {
        "provenance": _provenance(
            engine.name,
            engine.version,
            engine.architecture,
            engine.trained,
            engine.training_data,
            engine.notes,
        ),
        "purpose": (
            "Financial network risk detection. Scores accounts, transactions and "
            "whole clusters for structural similarity to known laundering "
            "topologies, AFTER transactions have settled."
        ),
        "architecture": engine.architecture,
        "graph_summary": {
            "live_accounts_nodes": account_count,
            "live_transactions_edges": txn_count,
            "clusters_detected": network_count,
            "clusters_flagged_suspicious": suspicious_count,
            "node_feature_count": len(NODE_FEATURE_SPEC),
            "edge_feature_count": len(EDGE_FEATURE_SPEC),
            "node_features": [
                {"name": name, "label": label} for name, label in NODE_FEATURE_SPEC
            ],
            "edge_features": [
                {"name": name, "label": label} for name, label in EDGE_FEATURE_SPEC
            ],
            "training_dataset": dataset_summary,
        },
        "tasks": [
            {
                "name": "Node risk",
                "type": "Node classification",
                "detail": "Per-account probability of belonging to a laundering structure.",
                "metric": _task_metric(metrics, "node_classification"),
            },
            {
                "name": "Edge risk",
                "type": "Edge scoring",
                "detail": "Per-transaction score from both endpoint embeddings plus edge features.",
                "metric": _task_metric(metrics, "edge_scoring"),
            },
            {
                "name": "Suspicious subgraph detection",
                "type": "Graph classification",
                "detail": "Whole-cluster readout over mean+max pooled node embeddings.",
                "metric": _task_metric(metrics, "subgraph_detection"),
            },
        ],
        "hyperparameters": hyperparameters,
        "metrics": metrics,
        "trained_at": engine.trained_at,
        "signal_vocabulary": _signal_vocabulary(),
        "caveats": caveats,
    }


def _task_metric(metrics: Optional[Dict[str, Any]], key: str) -> str:
    if not metrics or key not in metrics:
        return "not reported (no trained artifact)"
    block = metrics[key]
    return (
        f"F1 {block.get('f1', 0):.3f} / precision {block.get('precision', 0):.3f} "
        f"/ recall {block.get('recall', 0):.3f}"
    )


def _signal_vocabulary() -> List[Dict[str, str]]:
    from app.gnn.explain import SIGNAL_VOCABULARY

    return SIGNAL_VOCABULARY


def build_insights(db: Session) -> Dict[str, Any]:
    return {
        "proactive": proactive_card(),
        "gnn": gnn_card(db),
        "honesty_statement": HONESTY_STATEMENT,
    }
