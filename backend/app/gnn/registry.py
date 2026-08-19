"""GNN engine registry.

Selection order (controlled by `GNN_ENGINE` in the environment):
  auto     - trained PyTorch checkpoint if present, else the analytic engine
  torch    - require the trained checkpoint; raise if it cannot be loaded
  analytic - force the untrained heuristic engine
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from app.core.config import settings
from app.gnn.analytic import AnalyticGNNEngine
from app.gnn.base import GNNInferenceEngine

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_engine: Optional[GNNInferenceEngine] = None


def _load() -> GNNInferenceEngine:
    mode = (settings.gnn_engine or "auto").lower()

    if mode == "analytic":
        logger.info("GNN_ENGINE=analytic - using the untrained analytic engine")
        return AnalyticGNNEngine()

    path = settings.gnn_model_abspath
    if path.exists():
        from app.gnn.torch_gnn import load_engine

        engine = load_engine(path)
        if engine is not None:
            logger.info("Loaded trained GNN %s v%s", engine.name, engine.version)
            return engine
        if mode == "torch":
            raise RuntimeError(f"GNN_ENGINE=torch but the checkpoint at {path} failed to load")
    elif mode == "torch":
        raise RuntimeError(
            f"GNN_ENGINE=torch but no checkpoint exists at {path}. "
            "Run `python -m seed.seed` to train one."
        )

    logger.warning(
        "No trained GNN checkpoint at %s - falling back to the analytic engine "
        "(reported as untrained). Run `python -m seed.seed` to train one.",
        path,
    )
    return AnalyticGNNEngine()


def get_gnn_engine() -> GNNInferenceEngine:
    """Process-wide singleton for the active graph-risk engine."""
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                _engine = _load()
    return _engine


def reload_gnn_engine() -> GNNInferenceEngine:
    global _engine
    with _lock:
        _engine = None
    return get_gnn_engine()
