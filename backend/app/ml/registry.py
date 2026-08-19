"""Model registry: loads the active proactive model, with graceful fallback."""

from __future__ import annotations

import logging
import threading
from typing import Optional

from app.core.config import settings
from app.ml.model import HeuristicRiskModel, ProactiveRiskModel, RandomForestRiskModel

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_model: Optional[ProactiveRiskModel] = None


def _load() -> ProactiveRiskModel:
    path = settings.ml_model_abspath
    if not path.exists():
        logger.warning(
            "No proactive model artifact at %s - falling back to the untrained "
            "heuristic scorer. Run `python -m seed.seed` to train one.",
            path,
        )
        return HeuristicRiskModel()

    try:
        import joblib

        artifact = joblib.load(path)
        model = RandomForestRiskModel(artifact)
        logger.info("Loaded proactive model %s v%s", model.name, model.version)
        return model
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to load proactive model from %s: %s", path, exc)
        return HeuristicRiskModel()


def get_proactive_model() -> ProactiveRiskModel:
    """Process-wide singleton for the active proactive model."""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = _load()
    return _model


def reload_proactive_model() -> ProactiveRiskModel:
    """Force a reload, e.g. straight after retraining during seeding."""
    global _model
    with _lock:
        _model = None
    return get_proactive_model()
