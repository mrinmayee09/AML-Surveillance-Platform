"""Trainer for the proactive behavioural risk model.

WHAT IS REAL HERE
-----------------
The RandomForest is genuinely fitted, evaluated on a held-out split, and the
reported accuracy/precision/recall/F1/confusion matrix come from that split.

WHAT IS SIMULATED
-----------------
The *labels*. A production AML model is trained on confirmed SAR/STR outcomes.
No such ground truth exists for a prototype, so this module samples behavioural
feature vectors from archetype-conditional distributions and uses the archetype
as a weak label, with deliberate label noise and overlapping distributions so
the task is non-trivial. Metrics therefore describe how well the model recovers
a *synthetic* labelling function - not real-world laundering detection skill.
This caveat is surfaced verbatim on the Model Insights page.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.ml.features import FEATURE_NAMES, to_matrix

MODEL_NAME = "proactive_rf"
MODEL_VERSION = "1.0.0"
RANDOM_STATE = 20240817
LABEL_NOISE = 0.07  # fraction of labels intentionally flipped

TRAINING_DATA_DESCRIPTION = (
    "18,000 synthetic behavioural feature vectors sampled from eight customer "
    "archetypes (legitimate and laundering-typology), with 7% label noise. "
    "Labels are weak/synthetic - not confirmed SAR outcomes."
)

HYPERPARAMETERS: Dict[str, Any] = {
    "n_estimators": 300,
    "max_depth": 12,
    "min_samples_leaf": 6,
    "min_samples_split": 12,
    "max_features": "sqrt",
    "class_weight": "balanced_subsample",
    "criterion": "gini",
    "random_state": RANDOM_STATE,
    "n_jobs": -1,
}

# ---------------------------------------------------------------------------
# Archetype-conditional generative process
# ---------------------------------------------------------------------------
# Each archetype defines (mean, sigma) per feature in the model's own units.
# Distributions deliberately overlap so the classifier cannot trivially separate
# them, and `suspicious` marks which archetypes carry the positive weak label.

ARCHETYPES: Dict[str, Dict[str, Any]] = {
    "RETAIL_STABLE": {
        "weight": 0.30,
        "suspicious": False,
        "params": {
            "amount_deviation_ratio": (1.05, 0.35),
            "amount_log": (9.3, 0.7),
            "txn_count_30d": (14, 6),
            "frequency_ratio": (1.02, 0.25),
            "velocity_per_hour": (1.3, 0.7),
            "burst_score": (0.12, 0.07),
            "unique_counterparties_30d": (5, 2.5),
            "new_counterparties_30d": (0.8, 0.9),
            "counterparty_growth_ratio": (1.05, 0.3),
            "rapid_movement_score": (0.14, 0.1),
            "structuring_score": (0.04, 0.04),
            "round_amount_ratio": (0.22, 0.12),
            "international_share": (0.02, 0.04),
            "high_risk_geo_exposure": (0.0, 0.02),
            "account_age_years": (5.5, 2.8),
            "previous_alert_count": (0.05, 0.25),
            "dormancy_reactivation": (0.0, 0.05),
            "pep_flag": (0.01, 0.1),
        },
    },
    "SALARIED_LOW_ACTIVITY": {
        "weight": 0.14,
        "suspicious": False,
        "params": {
            "amount_deviation_ratio": (1.0, 0.3),
            "amount_log": (9.9, 0.6),
            "txn_count_30d": (7, 3),
            "frequency_ratio": (1.0, 0.2),
            "velocity_per_hour": (1.1, 0.4),
            "burst_score": (0.1, 0.05),
            "unique_counterparties_30d": (3, 1.5),
            "new_counterparties_30d": (0.4, 0.6),
            "counterparty_growth_ratio": (1.0, 0.2),
            "rapid_movement_score": (0.1, 0.08),
            "structuring_score": (0.03, 0.03),
            "round_amount_ratio": (0.3, 0.15),
            "international_share": (0.01, 0.03),
            "high_risk_geo_exposure": (0.0, 0.01),
            "account_age_years": (7.5, 3.5),
            "previous_alert_count": (0.02, 0.15),
            "dormancy_reactivation": (0.0, 0.03),
            "pep_flag": (0.01, 0.1),
        },
    },
    "SME_HIGH_VALUE_LEGIT": {
        # Deliberate hard negative: big, frequent, cross-border - but legitimate.
        "weight": 0.13,
        "suspicious": False,
        "params": {
            "amount_deviation_ratio": (1.4, 0.6),
            "amount_log": (12.4, 0.9),
            "txn_count_30d": (95, 35),
            "frequency_ratio": (1.15, 0.35),
            "velocity_per_hour": (5.5, 3.0),
            "burst_score": (0.2, 0.1),
            "unique_counterparties_30d": (42, 18),
            "new_counterparties_30d": (5.0, 3.0),
            "counterparty_growth_ratio": (1.2, 0.4),
            "rapid_movement_score": (0.3, 0.15),
            "structuring_score": (0.05, 0.05),
            "round_amount_ratio": (0.35, 0.15),
            "international_share": (0.28, 0.15),
            "high_risk_geo_exposure": (0.04, 0.05),
            "account_age_years": (9.0, 3.5),
            "previous_alert_count": (0.4, 0.7),
            "dormancy_reactivation": (0.0, 0.05),
            "pep_flag": (0.03, 0.17),
        },
    },
    "VOLATILE_LEGIT": {
        # Second hard negative: erratic but explainable behaviour.
        "weight": 0.10,
        "suspicious": False,
        "params": {
            "amount_deviation_ratio": (3.2, 1.6),
            "amount_log": (10.6, 1.2),
            "txn_count_30d": (30, 18),
            "frequency_ratio": (2.0, 0.9),
            "velocity_per_hour": (3.5, 2.0),
            "burst_score": (0.3, 0.14),
            "unique_counterparties_30d": (12, 7),
            "new_counterparties_30d": (3.5, 2.2),
            "counterparty_growth_ratio": (1.9, 0.8),
            "rapid_movement_score": (0.3, 0.16),
            "structuring_score": (0.08, 0.06),
            "round_amount_ratio": (0.3, 0.15),
            "international_share": (0.08, 0.08),
            "high_risk_geo_exposure": (0.02, 0.04),
            "account_age_years": (3.5, 2.0),
            "previous_alert_count": (0.6, 0.9),
            "dormancy_reactivation": (0.05, 0.2),
            "pep_flag": (0.02, 0.14),
        },
    },
    "STRUCTURING": {
        "weight": 0.08,
        "suspicious": True,
        "params": {
            "amount_deviation_ratio": (2.1, 1.0),
            "amount_log": (11.2, 0.5),
            "txn_count_30d": (110, 45),
            "frequency_ratio": (4.5, 1.8),
            "velocity_per_hour": (9.0, 4.5),
            "burst_score": (0.45, 0.15),
            "unique_counterparties_30d": (16, 8),
            "new_counterparties_30d": (7.0, 3.5),
            "counterparty_growth_ratio": (2.8, 1.1),
            "rapid_movement_score": (0.4, 0.18),
            "structuring_score": (0.62, 0.16),
            "round_amount_ratio": (0.15, 0.1),
            "international_share": (0.07, 0.08),
            "high_risk_geo_exposure": (0.05, 0.07),
            "account_age_years": (2.4, 1.6),
            "previous_alert_count": (1.4, 1.2),
            "dormancy_reactivation": (0.1, 0.3),
            "pep_flag": (0.03, 0.17),
        },
    },
    "LAYERING_MULE": {
        "weight": 0.09,
        "suspicious": True,
        "params": {
            "amount_deviation_ratio": (7.5, 3.2),
            "amount_log": (13.1, 0.8),
            "txn_count_30d": (55, 25),
            "frequency_ratio": (5.5, 2.2),
            "velocity_per_hour": (12.0, 6.0),
            "burst_score": (0.55, 0.16),
            "unique_counterparties_30d": (26, 12),
            "new_counterparties_30d": (14.0, 6.0),
            "counterparty_growth_ratio": (5.5, 2.2),
            "rapid_movement_score": (0.86, 0.11),
            "structuring_score": (0.2, 0.14),
            "round_amount_ratio": (0.55, 0.18),
            "international_share": (0.2, 0.14),
            "high_risk_geo_exposure": (0.18, 0.14),
            "account_age_years": (1.1, 0.8),
            "previous_alert_count": (1.8, 1.4),
            "dormancy_reactivation": (0.3, 0.45),
            "pep_flag": (0.02, 0.14),
        },
    },
    "RAPID_PASS_THROUGH": {
        "weight": 0.09,
        "suspicious": True,
        "params": {
            "amount_deviation_ratio": (5.0, 2.4),
            "amount_log": (12.6, 0.9),
            "txn_count_30d": (40, 20),
            "frequency_ratio": (3.4, 1.5),
            "velocity_per_hour": (16.0, 7.0),
            "burst_score": (0.62, 0.15),
            "unique_counterparties_30d": (14, 8),
            "new_counterparties_30d": (8.0, 4.0),
            "counterparty_growth_ratio": (3.4, 1.5),
            "rapid_movement_score": (0.92, 0.07),
            "structuring_score": (0.12, 0.1),
            "round_amount_ratio": (0.6, 0.2),
            "international_share": (0.15, 0.12),
            "high_risk_geo_exposure": (0.12, 0.12),
            "account_age_years": (1.6, 1.1),
            "previous_alert_count": (1.1, 1.1),
            "dormancy_reactivation": (0.25, 0.43),
            "pep_flag": (0.02, 0.14),
        },
    },
    "CROSS_BORDER_HIGH_RISK": {
        "weight": 0.07,
        "suspicious": True,
        "params": {
            "amount_deviation_ratio": (3.6, 1.8),
            "amount_log": (13.4, 0.9),
            "txn_count_30d": (28, 14),
            "frequency_ratio": (2.4, 1.1),
            "velocity_per_hour": (4.5, 2.5),
            "burst_score": (0.3, 0.14),
            "unique_counterparties_30d": (18, 9),
            "new_counterparties_30d": (9.0, 4.5),
            "counterparty_growth_ratio": (3.0, 1.3),
            "rapid_movement_score": (0.55, 0.2),
            "structuring_score": (0.14, 0.12),
            "round_amount_ratio": (0.45, 0.2),
            "international_share": (0.72, 0.16),
            "high_risk_geo_exposure": (0.6, 0.2),
            "account_age_years": (2.8, 1.8),
            "previous_alert_count": (1.2, 1.2),
            "dormancy_reactivation": (0.1, 0.3),
            "pep_flag": (0.18, 0.38),
        },
    },
}

FLAG_FEATURES = {"dormancy_reactivation", "pep_flag"}


def _sample_archetype(rng: np.random.Generator, spec: Dict[str, Any]) -> Dict[str, float]:
    row: Dict[str, float] = {}
    for name in FEATURE_NAMES:
        mean, sigma = spec["params"][name]
        value = float(rng.normal(mean, sigma))
        if name in FLAG_FEATURES:
            value = 1.0 if value >= 0.5 else 0.0
        row[name] = max(value, 0.0)
    return row


def generate_dataset(
    n_samples: int = 18_000, seed: int = RANDOM_STATE
) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """Sample the synthetic training set. Returns (X, y, archetype_names)."""
    rng = np.random.default_rng(seed)
    names = list(ARCHETYPES.keys())
    weights = np.array([ARCHETYPES[n]["weight"] for n in names], dtype=np.float64)
    weights = weights / weights.sum()

    rows: List[Dict[str, float]] = []
    labels: List[int] = []
    archetypes: List[str] = []

    picks = rng.choice(len(names), size=n_samples, p=weights)
    for pick in picks:
        arch_name = names[pick]
        spec = ARCHETYPES[arch_name]
        rows.append(_sample_archetype(rng, spec))
        label = 1 if spec["suspicious"] else 0
        # Deliberate label noise: real AML labelling is imperfect.
        if rng.random() < LABEL_NOISE:
            label = 1 - label
        labels.append(label)
        archetypes.append(arch_name)

    return to_matrix(rows), np.array(labels, dtype=np.int64), archetypes


def train(
    n_samples: int = 18_000, seed: int = RANDOM_STATE, verbose: bool = True
) -> Dict[str, Any]:
    """Fit the model and return a serialisable artifact dict."""
    X, y, _ = generate_dataset(n_samples=n_samples, seed=seed)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=seed, stratify=y
    )

    pipeline = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("forest", RandomForestClassifier(**HYPERPARAMETERS)),
        ]
    )
    pipeline.fit(X_train, y_train)

    y_pred = pipeline.predict(X_test)
    y_proba = pipeline.predict_proba(X_test)[:, list(pipeline.classes_).index(1)]

    cm = confusion_matrix(y_test, y_pred, labels=[0, 1])
    metrics = {
        "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
        "precision": round(float(precision_score(y_test, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_test, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_test, y_pred, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_test, y_proba)), 4),
        "support": int(len(y_test)),
        "confusion_matrix": cm.tolist(),
        "labels": ["Normal", "Elevated risk"],
    }

    forest: RandomForestClassifier = pipeline.named_steps["forest"]
    raw_importances = forest.feature_importances_
    total = float(raw_importances.sum()) or 1.0
    importances = {
        name: round(float(value) / total, 5)
        for name, value in zip(FEATURE_NAMES, raw_importances)
    }

    artifact: Dict[str, Any] = {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "pipeline": pipeline,
        "feature_names": FEATURE_NAMES,
        "feature_importances": importances,
        "metrics": metrics,
        "hyperparameters": HYPERPARAMETERS,
        "training_rows": int(len(y_train)),
        "class_balance": {
            "normal": int((y == 0).sum()),
            "elevated_risk": int((y == 1).sum()),
        },
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_data": TRAINING_DATA_DESCRIPTION,
        "notes": (
            "Fitted on synthetic archetype-conditional data with 7% label noise. "
            "Metrics measure recovery of a synthetic labelling function, not "
            "real-world laundering detection performance."
        ),
        "caveats": [
            "Labels are synthetic archetype weak labels, not confirmed SAR/STR outcomes.",
            "Two archetypes (SME_HIGH_VALUE_LEGIT, VOLATILE_LEGIT) are deliberate hard "
            "negatives so the model cannot separate classes on transaction size alone.",
            "Reported metrics come from a stratified 25% held-out split of the same "
            "synthetic distribution, so they will not transfer to production data.",
            "A risk score is a prioritisation signal for human review, never proof of "
            "criminal activity.",
        ],
    }

    if verbose:
        print(f"[ml] trained {MODEL_NAME} v{MODEL_VERSION} on {len(y_train):,} rows")
        print(
            f"[ml] holdout accuracy={metrics['accuracy']} precision={metrics['precision']} "
            f"recall={metrics['recall']} f1={metrics['f1']} auc={metrics['roc_auc']}"
        )
        top = sorted(importances.items(), key=lambda kv: kv[1], reverse=True)[:5]
        print("[ml] top features: " + ", ".join(f"{k}={v:.3f}" for k, v in top))

    return artifact


def save_artifact(artifact: Dict[str, Any], path: Path) -> Path:
    import joblib

    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, path)
    # Sidecar JSON so metrics are inspectable without unpickling
    meta = {k: v for k, v in artifact.items() if k != "pipeline"}
    path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path


def train_and_save(path: Path, n_samples: int = 18_000, verbose: bool = True) -> Path:
    artifact = train(n_samples=n_samples, verbose=verbose)
    return save_artifact(artifact, path)


if __name__ == "__main__":  # pragma: no cover
    from app.core.config import settings

    train_and_save(settings.ml_model_abspath)
