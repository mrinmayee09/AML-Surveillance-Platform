"""Proactive risk model interface + implementations.

Two implementations sit behind one interface so the scoring service never cares
which is active:

* `RandomForestRiskModel` - wraps a real fitted scikit-learn artifact.
* `HeuristicRiskModel`    - transparent weighted-signal fallback used when no
  artifact has been trained yet. It reports `trained=False` so the UI can say so.

Swapping in a gradient-boosted or neural model later means implementing
`ProactiveRiskModel` and registering it; nothing else changes.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from app.ml.features import (
    BASELINE_VECTOR,
    FEATURE_BY_NAME,
    FEATURE_NAMES,
    FEATURE_SPEC,
    INVERSE_FEATURES,
    describe_value,
    to_vector,
)


@dataclass
class Attribution:
    """One feature's model-derived contribution to the probability."""

    feature: str
    label: str
    category: str
    value: float
    value_display: str
    # Change in predicted probability caused by this feature moving from its
    # neutral baseline to its observed value (occlusion attribution).
    delta: float
    description: str = ""


@dataclass
class Prediction:
    probability: float
    attributions: List[Attribution] = field(default_factory=list)
    model_name: str = "unknown"
    model_version: str = "0.0.0"
    model_type: str = "unknown"
    trained: bool = False
    training_data: str = ""
    notes: str = ""
    trained_at: Optional[datetime] = None

    def provenance(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "model_type": self.model_type,
            "trained": self.trained,
            "training_data": self.training_data,
            "notes": self.notes,
        }


class ProactiveRiskModel(ABC):
    """Contract every proactive risk model must satisfy."""

    name: str = "abstract"
    version: str = "0.0.0"
    model_type: str = "abstract"
    trained: bool = False
    training_data: str = ""
    notes: str = ""
    trained_at: Optional[datetime] = None

    @abstractmethod
    def predict_proba(self, features: Dict[str, float]) -> float:
        """Return P(emerging elevated AML risk) in [0, 1]."""

    @abstractmethod
    def feature_importances(self) -> Dict[str, float]:
        """Global feature importance, normalised to sum to 1."""

    def _predict_vectors(self, matrix: np.ndarray) -> np.ndarray:
        """Score a (n, n_features) matrix.

        Single-row scikit-learn calls are dominated by per-call validation and
        pipeline overhead (~68ms each on the bundled forest), so anything that
        needs many predictions should route through here. Implementations that
        can vectorise MUST override this; the default falls back to a loop.
        """
        return np.array(
            [self._predict_vector(row) for row in np.atleast_2d(matrix)],
            dtype=np.float64,
        )

    def predict_proba_batch(self, rows: Sequence[Dict[str, float]]) -> np.ndarray:
        """Score many feature dicts in one call."""
        if not rows:
            return np.zeros(0, dtype=np.float64)
        return self._predict_vectors(np.vstack([to_vector(row) for row in rows]))

    def _explain(
        self, features: Dict[str, float]
    ) -> tuple[float, List[Attribution]]:
        """Probability and per-feature occlusion attribution in ONE model call.

        For each feature we recompute the prediction with that feature reset to
        its neutral baseline and record the drop in probability. This is a real
        model interrogation (a one-at-a-time occlusion / ablation attribution),
        not a hand-written score table - but it is also not exact Shapley, and
        the Model Insights page says so.

        The unmodified observation and all n occlusions are stacked into a single
        matrix, so a full explanation costs roughly one prediction rather than
        n + 1 of them.
        """
        vector = to_vector(features)

        # Row 0 is the unmodified observation; row i+1 occludes feature i
        rows = [vector]
        for idx, spec in enumerate(FEATURE_SPEC):
            occluded = vector.copy()
            occluded[idx] = spec.baseline
            rows.append(occluded)

        probabilities = self._predict_vectors(np.vstack(rows))
        base_prob = float(probabilities[0])

        attributions: List[Attribution] = []
        for idx, spec in enumerate(FEATURE_SPEC):
            attributions.append(
                Attribution(
                    feature=spec.name,
                    label=spec.label,
                    category=spec.category,
                    value=float(vector[idx]),
                    value_display=describe_value(spec.name, float(vector[idx])),
                    delta=base_prob - float(probabilities[idx + 1]),
                    description=spec.description,
                )
            )

        attributions.sort(key=lambda a: a.delta, reverse=True)
        return base_prob, attributions

    def attribute(self, features: Dict[str, float]) -> List[Attribution]:
        """Per-feature occlusion attribution for a single prediction."""
        return self._explain(features)[1]

    def predict(self, features: Dict[str, float]) -> Prediction:
        probability, attributions = self._explain(features)
        return Prediction(
            probability=probability,
            attributions=attributions,
            model_name=self.name,
            model_version=self.version,
            model_type=self.model_type,
            trained=self.trained,
            training_data=self.training_data,
            notes=self.notes,
            trained_at=self.trained_at,
        )

    @abstractmethod
    def _predict_vector(self, vector: np.ndarray) -> float:
        """Score a pre-ordered feature vector."""


class RandomForestRiskModel(ProactiveRiskModel):
    """Wraps a fitted sklearn Pipeline (scaler + RandomForestClassifier)."""

    model_type = "RandomForestClassifier (scikit-learn)"

    def __init__(self, artifact: Dict[str, Any]):
        self._pipeline = artifact["pipeline"]
        self._importances: Dict[str, float] = artifact.get("feature_importances", {})
        self.metrics: Dict[str, Any] = artifact.get("metrics", {})
        self.hyperparameters: Dict[str, Any] = artifact.get("hyperparameters", {})
        self.training_rows: int = int(artifact.get("training_rows", 0))
        self.class_balance: Dict[str, int] = artifact.get("class_balance", {})
        self.feature_names: List[str] = artifact.get("feature_names", FEATURE_NAMES)
        self.name = artifact.get("model_name", "proactive_rf")
        self.version = artifact.get("model_version", "1.0.0")
        self.trained = True
        self.training_data = artifact.get(
            "training_data",
            "Synthetic labelled behavioural feature vectors generated by the seed pipeline.",
        )
        self.notes = artifact.get("notes", "")
        trained_at = artifact.get("trained_at")
        self.trained_at = (
            datetime.fromisoformat(trained_at) if isinstance(trained_at, str) else trained_at
        )

        if self.feature_names != FEATURE_NAMES:
            raise ValueError(
                "Model artifact feature order does not match FEATURE_SPEC. "
                "Retrain with `python -m seed.seed --retrain-models`."
            )

    def _predict_vector(self, vector: np.ndarray) -> float:
        proba = self._pipeline.predict_proba(vector.reshape(1, -1))[0]
        # Column index of the positive ("elevated risk") class
        classes = list(self._pipeline.classes_)
        pos = classes.index(1) if 1 in classes else len(classes) - 1
        return float(proba[pos])

    def predict_proba(self, features: Dict[str, float]) -> float:
        return self._predict_vector(to_vector(features))

    def _predict_vectors(self, matrix: np.ndarray) -> np.ndarray:
        """One scikit-learn call for the whole matrix."""
        matrix = np.atleast_2d(matrix)
        if matrix.shape[0] == 0:
            return np.zeros(0, dtype=np.float64)
        proba = self._pipeline.predict_proba(matrix)
        classes = list(self._pipeline.classes_)
        pos = classes.index(1) if 1 in classes else len(classes) - 1
        return proba[:, pos].astype(np.float64)

    def feature_importances(self) -> Dict[str, float]:
        return dict(self._importances)


class HeuristicRiskModel(ProactiveRiskModel):
    """Transparent fallback scorer.

    Used only when no trained artifact is present. Every weight is visible here,
    and `trained` stays False so the platform never claims a fitted model exists.
    """

    name = "proactive_heuristic"
    version = "1.0.0"
    model_type = "Weighted logistic heuristic (not a fitted model)"
    trained = False
    training_data = "None - deterministic weights, no fitting performed."
    notes = (
        "Fallback scorer. Present so the platform degrades gracefully when no "
        "trained artifact is available. Reported as untrained everywhere."
    )

    WEIGHTS: Dict[str, float] = {
        "amount_deviation_ratio": 0.22,
        "frequency_ratio": 0.16,
        "velocity_per_hour": 0.10,
        "burst_score": 0.08,
        "new_counterparties_30d": 0.14,
        "counterparty_growth_ratio": 0.12,
        "rapid_movement_score": 0.20,
        "structuring_score": 0.16,
        "round_amount_ratio": 0.05,
        "international_share": 0.06,
        "high_risk_geo_exposure": 0.12,
        "previous_alert_count": 0.10,
        "dormancy_reactivation": 0.08,
        "pep_flag": 0.04,
        "unique_counterparties_30d": 0.04,
        "txn_count_30d": 0.04,
        "amount_log": 0.05,
        "account_age_years": -0.10,
    }
    # Scale each raw feature to roughly [0, 1] before weighting
    SCALES: Dict[str, float] = {
        "amount_deviation_ratio": 8.0,
        "frequency_ratio": 6.0,
        "velocity_per_hour": 20.0,
        "new_counterparties_30d": 15.0,
        "counterparty_growth_ratio": 6.0,
        "previous_alert_count": 5.0,
        "unique_counterparties_30d": 30.0,
        "txn_count_30d": 120.0,
        "amount_log": 16.0,
        "account_age_years": 8.0,
    }
    BIAS = -2.4

    def _predict_vector(self, vector: np.ndarray) -> float:
        logit = self.BIAS
        for name, value in zip(FEATURE_NAMES, vector):
            weight = self.WEIGHTS.get(name, 0.0)
            scale = self.SCALES.get(name, 1.0)
            logit += weight * min(float(value) / scale, 1.6) * 4.0
        return 1.0 / (1.0 + math.exp(-logit))

    def predict_proba(self, features: Dict[str, float]) -> float:
        return self._predict_vector(to_vector(features))

    def feature_importances(self) -> Dict[str, float]:
        magnitudes = {k: abs(v) for k, v in self.WEIGHTS.items()}
        total = sum(magnitudes.values()) or 1.0
        return {k: v / total for k, v in magnitudes.items()}


def positive_attributions(
    attributions: List[Attribution], min_delta: float = 0.004
) -> List[Attribution]:
    """Keep only aggravating signals worth showing to an investigator."""
    kept = []
    for attr in attributions:
        if attr.delta < min_delta:
            continue
        # A long-standing relationship should never read as an aggravating factor
        if attr.feature in INVERSE_FEATURES and attr.value >= (
            FEATURE_BY_NAME[attr.feature].baseline
        ):
            continue
        kept.append(attr)
    return kept


def baseline_probability(model: ProactiveRiskModel) -> float:
    """Model output for a perfectly average customer - the score's reference point."""
    return model._predict_vector(BASELINE_VECTOR.copy())  # noqa: SLF001
