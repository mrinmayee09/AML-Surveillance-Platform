"""GNN inference contract.

Every engine - the trained PyTorch model, the analytic fallback, or a future
PyTorch Geometric implementation - implements `GNNInferenceEngine`. Services
only ever talk to this interface, so replacing the model is a registry change.

`GNNOutput.provenance` forces every engine to declare whether it is a genuinely
trained model. The API and UI render that declaration verbatim rather than
assuming a score came from a neural network.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

from app.graph.types import GraphSnapshot


@dataclass
class GNNOutput:
    """Per-node, per-edge and whole-subgraph scores, all on a 0-100 scale."""

    node_scores: Dict[str, float] = field(default_factory=dict)
    edge_scores: Dict[str, float] = field(default_factory=dict)
    graph_score: float = 0.0
    # Learned node representations, retained for neighbourhood similarity work
    embeddings: Optional[np.ndarray] = None
    engine_name: str = "unknown"
    engine_version: str = "0.0.0"
    architecture: str = "unknown"
    trained: bool = False
    training_data: str = ""
    notes: str = ""

    def provenance(self) -> Dict[str, Any]:
        return {
            "model_name": self.engine_name,
            "model_version": self.engine_version,
            "model_type": self.architecture,
            "trained": self.trained,
            "training_data": self.training_data,
            "notes": self.notes,
        }

    def top_nodes(self, limit: int = 5) -> List[tuple[str, float]]:
        return sorted(self.node_scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]

    def top_edges(self, limit: int = 5) -> List[tuple[str, float]]:
        return sorted(self.edge_scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]


class GNNInferenceEngine(ABC):
    """Contract for graph-level AML risk inference."""

    name: str = "abstract"
    version: str = "0.0.0"
    architecture: str = "abstract"
    trained: bool = False
    training_data: str = ""
    notes: str = ""
    trained_at: Optional[datetime] = None
    metrics: Dict[str, Any] = {}

    @abstractmethod
    def infer(self, snapshot: GraphSnapshot) -> GNNOutput:
        """Score every node and edge in the snapshot, plus the graph as a whole."""

    def infer_subgraph(self, snapshot: GraphSnapshot, node_keys: List[str]) -> GNNOutput:
        """Score an induced subgraph.

        Default implementation re-featurises the subgraph so the readout head
        sees only the cluster. Engines may override for a full-graph context pass.
        """
        return self.infer(snapshot.subgraph(node_keys))

    def describe(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "architecture": self.architecture,
            "trained": self.trained,
            "training_data": self.training_data,
            "notes": self.notes,
            "trained_at": self.trained_at.isoformat() if self.trained_at else None,
            "metrics": self.metrics or {},
        }
