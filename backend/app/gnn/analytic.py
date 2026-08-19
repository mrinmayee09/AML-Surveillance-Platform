"""Analytic (untrained) graph-risk engine.

Used when PyTorch is unavailable or no checkpoint has been trained. It performs
real graph analysis - value-weighted PageRank-style centrality plus pass-through,
relay-speed and uniformity signals - but it is NOT a neural network and it
reports `trained=False`, so the platform never misrepresents it as one.

This exists so the surveillance pipeline degrades gracefully rather than
returning zeros, and so the difference between a trained GNN and a hand-weighted
heuristic stays visible in the UI.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np

from app.gnn.base import GNNInferenceEngine, GNNOutput
from app.graph.types import GraphSnapshot

ENGINE_NAME = "graph_analytic"
ENGINE_VERSION = "1.0.0"
ARCHITECTURE = (
    "Value-weighted centrality + structural signal heuristic "
    "(NOT a neural network, no learned parameters)"
)

# Hand-set weights. Visible on purpose: an untrained engine should not look
# like a black box.
NODE_WEIGHTS: Dict[str, float] = {
    "pass_through": 0.26,
    "relay_speed": 0.20,
    "centrality": 0.18,
    "degree": 0.12,
    "round_ratio": 0.08,
    "timing": 0.10,
    "youth": 0.06,
}


def _power_iteration_centrality(
    snapshot: GraphSnapshot, iterations: int = 30, damping: float = 0.85
) -> np.ndarray:
    """Value-weighted PageRank over the money-flow graph."""
    n = snapshot.num_nodes
    if n == 0:
        return np.zeros(0, dtype=np.float64)
    if snapshot.num_edges == 0:
        return np.full(n, 1.0 / n, dtype=np.float64)

    src = snapshot.edge_index[0]
    dst = snapshot.edge_index[1]
    # Weight each hop by transfer size so large flows carry more influence
    weights = snapshot.edge_features[:, 0].astype(np.float64) + 1e-6

    out_strength = np.zeros(n, dtype=np.float64)
    np.add.at(out_strength, src, weights)

    rank = np.full(n, 1.0 / n, dtype=np.float64)
    for _ in range(iterations):
        contrib = np.zeros(n, dtype=np.float64)
        share = rank[src] * weights / np.maximum(out_strength[src], 1e-12)
        np.add.at(contrib, dst, share)
        # Dangling nodes redistribute uniformly
        dangling = rank[out_strength == 0].sum()
        rank = (1 - damping) / n + damping * (contrib + dangling / n)
        total = rank.sum()
        if total > 0:
            rank = rank / total
    return rank


class AnalyticGNNEngine(GNNInferenceEngine):
    name = ENGINE_NAME
    version = ENGINE_VERSION
    architecture = ARCHITECTURE
    trained = False
    training_data = "None - deterministic weights, no fitting performed."
    notes = (
        "Fallback graph-risk engine. Performs genuine structural analysis but has "
        "no learned parameters and must not be described as a GNN."
    )
    metrics: Dict[str, object] = {}

    def infer(self, snapshot: GraphSnapshot) -> GNNOutput:
        if snapshot.num_nodes == 0:
            return GNNOutput(
                engine_name=self.name,
                engine_version=self.version,
                architecture=self.architecture,
                trained=False,
                training_data=self.training_data,
                notes=self.notes,
            )

        centrality = _power_iteration_centrality(snapshot)
        centrality_norm = centrality / max(centrality.max(), 1e-12)

        node_scores: Dict[str, float] = {}
        for idx, key in enumerate(snapshot.node_keys):
            features = snapshot.node_features[idx]
            stats = snapshot.node_stats.get(key, {})
            degree = stats.get("degree_in", 0.0) + stats.get("degree_out", 0.0)

            components = {
                "pass_through": float(features[4]),
                "relay_speed": float(features[15]),
                "centrality": float(centrality_norm[idx]),
                "degree": min(degree / 20.0, 1.0),
                "round_ratio": float(features[12]),
                "timing": float(features[9]),
                "youth": 1.0 - float(features[8]),
            }
            raw = sum(NODE_WEIGHTS[k] * v for k, v in components.items())
            node_scores[key] = round(min(raw, 1.0) * 100.0, 2)

        edge_scores: Dict[str, float] = {}
        for i, key in enumerate(snapshot.edge_keys):
            row = snapshot.edge_features[i]
            src_key = snapshot.node_keys[snapshot.edge_index[0, i]]
            dst_key = snapshot.node_keys[snapshot.edge_index[1, i]]
            endpoint_risk = (node_scores[src_key] + node_scores[dst_key]) / 2.0
            edge_signal = (
                0.30 * float(row[0])  # size
                + 0.26 * float(row[3])  # relay latency
                + 0.16 * float(row[1])  # share of sender outflow
                + 0.16 * float(row[2])  # share of receiver inflow
                + 0.12 * float(row[5])  # round amount
            ) * 100.0
            edge_scores[key] = round(min(0.55 * endpoint_risk + 0.45 * edge_signal, 100.0), 2)

        values = list(node_scores.values())
        # Readout: blend the worst node with the cluster average
        graph_score = round(0.6 * max(values) + 0.4 * (sum(values) / len(values)), 2)

        return GNNOutput(
            node_scores=node_scores,
            edge_scores=edge_scores,
            graph_score=graph_score,
            embeddings=None,
            engine_name=self.name,
            engine_version=self.version,
            architecture=self.architecture,
            trained=False,
            training_data=self.training_data,
            notes=self.notes,
        )
