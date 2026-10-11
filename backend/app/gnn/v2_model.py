"""Loading a trained window GNN checkpoint (written by R2 / R3).

A checkpoint is self-describing - architecture variant, feature schema, window
shape and decision threshold all travel with the weights - so whoever loads it
(the R4 fidelity test, the app) featurises and thresholds exactly as training did.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

from app.core.config import BACKEND_ROOT
from app.graph.features_v2 import FeatureSchema, WindowConfig

# Where R3 exports the selected model and the app loads it from.
# GNN_V2_MODEL_PATH overrides it (e.g. to try a different checkpoint).
EXPORT_PATH = Path(
    os.environ.get("GNN_V2_MODEL_PATH")
    or BACKEND_ROOT / "app" / "gnn" / "artifacts" / "aml_gnn_v2.pt"
)


@dataclass
class LoadedModel:
    model: Any
    variant: str
    schema: FeatureSchema
    window: WindowConfig
    threshold: float
    name: str
    training_data: str
    metrics: Dict[str, Any] = field(default_factory=dict)
    path: str = ""


def load_checkpoint(path: Path) -> LoadedModel:
    import torch

    from app.gnn.sage import build_model

    ckpt = torch.load(Path(path), map_location="cpu", weights_only=False)
    cfg = ckpt["config"]
    variant = ckpt.get("variant", "directed")  # R2 checkpoints predate the field
    model = build_model(variant, cfg["node_dim"], cfg["edge_dim"], cfg["hidden"], cfg["layers"], 0.0)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    return LoadedModel(
        model=model,
        variant=variant,
        schema=FeatureSchema.from_dict(ckpt["schema"]),
        window=WindowConfig(**ckpt["window"]),
        threshold=float(ckpt["threshold"]),
        name=ckpt.get("model_name", "aml_gnn_v2"),
        training_data=ckpt.get("training_data", ""),
        metrics=ckpt.get("metrics", {}),
        path=str(path),
    )
