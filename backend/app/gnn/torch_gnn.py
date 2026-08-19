"""A real graph neural network for AML network risk, in plain PyTorch.

Architecture
------------
Directed, value-weighted GraphSAGE-style message passing. Each layer aggregates
separately over a node's *inbound* and *outbound* neighbourhoods, because in a
money-flow graph "who paid me" and "who I paid" are different signals - a
collapsed undirected mean would destroy exactly the asymmetry that distinguishes
a collection account from a distributor.

Three heads share the encoder:
  * node head    -> per-account risk (node classification)
  * edge head    -> per-transaction risk from both endpoint embeddings + edge features
  * readout head -> whole-subgraph risk from mean+max pooling (graph classification)

Sparse aggregation uses `Tensor.index_add_`, so no PyTorch Geometric dependency
is required. `app/gnn/pyg_adapter.py` documents the drop-in swap if PyG is
installed later.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import numpy as np

from app.gnn.base import GNNInferenceEngine, GNNOutput
from app.graph.types import (
    EDGE_FEATURE_DIM,
    NODE_FEATURE_DIM,
    GraphSnapshot,
)

logger = logging.getLogger(__name__)

try:  # torch is optional; the registry falls back to the analytic engine
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    TORCH_AVAILABLE = False
    torch = None  # type: ignore
    nn = None  # type: ignore


MODEL_NAME = "aml_gnn"
MODEL_VERSION = "1.0.0"
ARCHITECTURE = (
    "Directed value-weighted GraphSAGE encoder (3 layers, 64-dim) with node, "
    "edge and graph-readout heads - implemented directly in PyTorch"
)
HIDDEN_DIM = 64
NUM_LAYERS = 3


if TORCH_AVAILABLE:

    def _scatter_mean(
        source: "torch.Tensor", index: "torch.Tensor", num_nodes: int
    ) -> "torch.Tensor":
        """Mean-aggregate `source` rows into `num_nodes` buckets given by `index`."""
        out = torch.zeros(
            num_nodes, source.size(1), dtype=source.dtype, device=source.device
        )
        counts = torch.zeros(num_nodes, 1, dtype=source.dtype, device=source.device)
        if source.size(0) > 0:
            out.index_add_(0, index, source)
            counts.index_add_(
                0, index, torch.ones(source.size(0), 1, dtype=source.dtype, device=source.device)
            )
        return out / counts.clamp(min=1.0)

    class DirectedSAGELayer(nn.Module):
        """One round of direction-aware, value-weighted message passing."""

        def __init__(self, in_dim: int, out_dim: int):
            super().__init__()
            self.lin_self = nn.Linear(in_dim, out_dim)
            # Messages arriving along the direction of money flow (src -> dst)
            self.lin_inbound = nn.Linear(in_dim, out_dim)
            # Messages travelling back against the flow (dst -> src)
            self.lin_outbound = nn.Linear(in_dim, out_dim)
            self.norm = nn.LayerNorm(out_dim)

        def forward(
            self,
            x: "torch.Tensor",
            edge_index: "torch.Tensor",
            edge_weight: "torch.Tensor",
        ) -> "torch.Tensor":
            num_nodes = x.size(0)
            if edge_index.numel() == 0:
                return self.norm(F.relu(self.lin_self(x)))

            src, dst = edge_index[0], edge_index[1]
            weight = edge_weight.view(-1, 1)

            # What flowed INTO each node, weighted by transfer size
            inbound = _scatter_mean(x[src] * weight, dst, num_nodes)
            # What each node sent OUT, weighted the same way
            outbound = _scatter_mean(x[dst] * weight, src, num_nodes)

            h = self.lin_self(x) + self.lin_inbound(inbound) + self.lin_outbound(outbound)
            return self.norm(F.relu(h))

    class AmlGNN(nn.Module):
        """Shared encoder with node / edge / graph heads."""

        def __init__(
            self,
            node_dim: int = NODE_FEATURE_DIM,
            edge_dim: int = EDGE_FEATURE_DIM,
            hidden: int = HIDDEN_DIM,
            layers: int = NUM_LAYERS,
            dropout: float = 0.15,
        ):
            super().__init__()
            self.input_proj = nn.Linear(node_dim, hidden)
            self.convs = nn.ModuleList(
                [DirectedSAGELayer(hidden, hidden) for _ in range(layers)]
            )
            self.dropout = nn.Dropout(dropout)

            self.node_head = nn.Sequential(
                nn.Linear(hidden, 32), nn.ReLU(), nn.Dropout(dropout), nn.Linear(32, 1)
            )
            self.edge_head = nn.Sequential(
                nn.Linear(hidden * 2 + edge_dim, 64),
                nn.ReLU(),
                nn.Dropout(dropout),
                nn.Linear(64, 1),
            )
            # Readout consumes mean+max pooled embeddings
            self.graph_head = nn.Sequential(
                nn.Linear(hidden * 2, 64), nn.ReLU(), nn.Linear(64, 1)
            )

        def encode(
            self,
            x: "torch.Tensor",
            edge_index: "torch.Tensor",
            edge_weight: "torch.Tensor",
        ) -> "torch.Tensor":
            h = F.relu(self.input_proj(x))
            for conv in self.convs:
                h = self.dropout(conv(h, edge_index, edge_weight))
            return h

        def forward(
            self,
            x: "torch.Tensor",
            edge_index: "torch.Tensor",
            edge_attr: "torch.Tensor",
        ) -> Tuple["torch.Tensor", "torch.Tensor", "torch.Tensor", "torch.Tensor"]:
            # Feature 0 of every edge is the log-scaled amount: use it to weight
            # messages so large transfers dominate the neighbourhood summary.
            edge_weight = (
                edge_attr[:, 0] if edge_attr.numel() else torch.zeros(0, device=x.device)
            )
            h = self.encode(x, edge_index, edge_weight)

            node_logits = self.node_head(h).squeeze(-1)

            if edge_index.numel():
                src_h, dst_h = h[edge_index[0]], h[edge_index[1]]
                edge_logits = self.edge_head(
                    torch.cat([src_h, dst_h, edge_attr], dim=1)
                ).squeeze(-1)
            else:
                edge_logits = torch.zeros(0, device=x.device)

            pooled = torch.cat([h.mean(dim=0), h.max(dim=0).values], dim=0)
            graph_logit = self.graph_head(pooled).squeeze()

            return node_logits, edge_logits, graph_logit, h


class TorchGNNEngine(GNNInferenceEngine):
    """Inference wrapper around a trained `AmlGNN` checkpoint."""

    def __init__(self, checkpoint: Dict[str, Any]):
        if not TORCH_AVAILABLE:  # pragma: no cover
            raise RuntimeError("PyTorch is not installed")

        self.name = checkpoint.get("model_name", MODEL_NAME)
        self.version = checkpoint.get("model_version", MODEL_VERSION)
        self.architecture = checkpoint.get("architecture", ARCHITECTURE)
        self.trained = True
        self.training_data = checkpoint.get("training_data", "")
        self.notes = checkpoint.get("notes", "")
        self.metrics = checkpoint.get("metrics", {})
        self.hyperparameters = checkpoint.get("hyperparameters", {})
        self.dataset_summary = checkpoint.get("dataset_summary", {})
        self.caveats = checkpoint.get("caveats", [])
        trained_at = checkpoint.get("trained_at")
        self.trained_at = (
            datetime.fromisoformat(trained_at) if isinstance(trained_at, str) else trained_at
        )

        config = checkpoint.get("config", {})
        self.model = AmlGNN(
            node_dim=config.get("node_dim", NODE_FEATURE_DIM),
            edge_dim=config.get("edge_dim", EDGE_FEATURE_DIM),
            hidden=config.get("hidden", HIDDEN_DIM),
            layers=config.get("layers", NUM_LAYERS),
            dropout=0.0,  # inference: no dropout
        )
        self.model.load_state_dict(checkpoint["state_dict"])
        self.model.eval()

    def infer(self, snapshot: GraphSnapshot) -> GNNOutput:
        if snapshot.num_nodes == 0:
            return self._empty_output()

        x = torch.from_numpy(snapshot.node_features.astype(np.float32))
        edge_index = torch.from_numpy(snapshot.edge_index.astype(np.int64))
        edge_attr = torch.from_numpy(snapshot.edge_features.astype(np.float32))

        with torch.no_grad():
            node_logits, edge_logits, graph_logit, embeddings = self.model(
                x, edge_index, edge_attr
            )

        node_probs = torch.sigmoid(node_logits).cpu().numpy()
        edge_probs = (
            torch.sigmoid(edge_logits).cpu().numpy()
            if edge_logits.numel()
            else np.zeros(0, dtype=np.float32)
        )
        graph_prob = float(torch.sigmoid(graph_logit).cpu().item())

        return GNNOutput(
            node_scores={
                key: round(float(p) * 100.0, 2)
                for key, p in zip(snapshot.node_keys, node_probs)
            },
            edge_scores={
                key: round(float(p) * 100.0, 2)
                for key, p in zip(snapshot.edge_keys, edge_probs)
            },
            graph_score=round(graph_prob * 100.0, 2),
            embeddings=embeddings.cpu().numpy(),
            engine_name=self.name,
            engine_version=self.version,
            architecture=self.architecture,
            trained=True,
            training_data=self.training_data,
            notes=self.notes,
        )

    def _empty_output(self) -> GNNOutput:
        return GNNOutput(
            engine_name=self.name,
            engine_version=self.version,
            architecture=self.architecture,
            trained=True,
            training_data=self.training_data,
            notes=self.notes,
        )


def load_engine(path) -> Optional[TorchGNNEngine]:
    """Load a checkpoint, returning None if unavailable or incompatible."""
    if not TORCH_AVAILABLE:
        logger.warning("PyTorch not installed - cannot load the trained GNN")
        return None
    try:
        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
        return TorchGNNEngine(checkpoint)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to load GNN checkpoint %s: %s", path, exc)
        return None
