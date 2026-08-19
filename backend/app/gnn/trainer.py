"""Trains the AML graph neural network.

WHAT IS REAL HERE
-----------------
The network is a genuine GNN: real message passing, real backpropagation, three
supervised objectives (node / edge / graph), and metrics computed on graphs the
model never saw during training. Nothing about the scores it produces at
inference time is hard-coded.

WHAT IS SIMULATED
-----------------
The training graphs. They come from `app.graph.synthetic`, which injects known
laundering topologies (layering chains, circular flows, smurfing fan-ins, rapid
fan-out dispersion) alongside benign look-alikes (merchant collections, payroll
runs, trade chains). Labels are therefore *structural ground truth by
construction*, not adjudicated criminal outcomes.

So the honest claim is: this model has really learned to recognise laundering
*topologies*. It has not learned, and cannot claim, to identify money launderers.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

from app.graph.synthetic import LabelledGraph, dataset_summary, generate_dataset
from app.graph.types import EDGE_FEATURE_DIM, NODE_FEATURE_DIM

logger = logging.getLogger(__name__)

try:
    import torch
    import torch.nn as nn

    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    TORCH_AVAILABLE = False

from app.gnn.torch_gnn import (  # noqa: E402  (import after torch probe)
    ARCHITECTURE,
    HIDDEN_DIM,
    MODEL_NAME,
    MODEL_VERSION,
    NUM_LAYERS,
    AmlGNN,
)

RANDOM_SEED = 424242
EPOCHS = 26
LEARNING_RATE = 3e-3
WEIGHT_DECAY = 1e-4
BATCH_GRAPHS = 8  # graphs accumulated per optimiser step
NODE_LOSS_WEIGHT = 1.0
EDGE_LOSS_WEIGHT = 1.0
GRAPH_LOSS_WEIGHT = 0.6

TRAINING_DATA_DESCRIPTION = (
    "900 synthetic transaction graphs (~26k nodes / ~42k edges) with injected "
    "laundering topologies and benign look-alike structures. Node, edge and "
    "graph labels are structural ground truth by construction - not confirmed "
    "laundering cases."
)


def _to_tensors(graph: LabelledGraph):
    snap = graph.snapshot
    return (
        torch.from_numpy(snap.node_features.astype(np.float32)),
        torch.from_numpy(snap.edge_index.astype(np.int64)),
        torch.from_numpy(snap.edge_features.astype(np.float32)),
        torch.from_numpy(graph.node_labels.astype(np.float32)),
        torch.from_numpy(graph.edge_labels.astype(np.float32)),
        torch.tensor(float(graph.graph_label)),
    )


def _binary_metrics(
    y_true: np.ndarray, y_prob: np.ndarray, threshold: float = 0.5
) -> Dict[str, Any]:
    """Accuracy / precision / recall / F1 / AUC + confusion matrix."""
    if y_true.size == 0:
        return {
            "accuracy": 0.0,
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "roc_auc": None,
            "support": 0,
            "confusion_matrix": [[0, 0], [0, 0]],
        }

    y_pred = (y_prob >= threshold).astype(np.int64)
    y_true_i = y_true.astype(np.int64)

    tp = int(((y_pred == 1) & (y_true_i == 1)).sum())
    tn = int(((y_pred == 0) & (y_true_i == 0)).sum())
    fp = int(((y_pred == 1) & (y_true_i == 0)).sum())
    fn = int(((y_pred == 0) & (y_true_i == 1)).sum())

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    roc_auc: float | None = None
    if 0 < y_true_i.sum() < y_true_i.size:
        # Rank-based AUC (Mann-Whitney U), avoids a sklearn dependency here
        order = np.argsort(y_prob)
        ranks = np.empty_like(order, dtype=np.float64)
        ranks[order] = np.arange(1, len(y_prob) + 1)
        pos = y_true_i == 1
        n_pos, n_neg = int(pos.sum()), int((~pos).sum())
        roc_auc = float(
            (ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
        )

    return {
        "accuracy": round((tp + tn) / len(y_true_i), 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "roc_auc": round(roc_auc, 4) if roc_auc is not None else None,
        "support": int(len(y_true_i)),
        "positives": int(y_true_i.sum()),
        "confusion_matrix": [[tn, fp], [fn, tp]],
        "labels": ["Not in flagged structure", "In flagged structure"],
    }


def _evaluate(model: "AmlGNN", graphs: Sequence[LabelledGraph]) -> Dict[str, Any]:
    model.eval()
    node_true, node_prob = [], []
    edge_true, edge_prob = [], []
    graph_true, graph_prob = [], []

    with torch.no_grad():
        for graph in graphs:
            x, edge_index, edge_attr, y_node, y_edge, y_graph = _to_tensors(graph)
            n_logits, e_logits, g_logit, _ = model(x, edge_index, edge_attr)
            node_true.append(y_node.numpy())
            node_prob.append(torch.sigmoid(n_logits).numpy())
            if e_logits.numel():
                edge_true.append(y_edge.numpy())
                edge_prob.append(torch.sigmoid(e_logits).numpy())
            graph_true.append(float(y_graph))
            graph_prob.append(float(torch.sigmoid(g_logit)))

    return {
        "node_classification": _binary_metrics(
            np.concatenate(node_true), np.concatenate(node_prob)
        ),
        "edge_scoring": _binary_metrics(
            np.concatenate(edge_true) if edge_true else np.zeros(0),
            np.concatenate(edge_prob) if edge_prob else np.zeros(0),
        ),
        "subgraph_detection": _binary_metrics(
            np.array(graph_true), np.array(graph_prob)
        ),
    }


def train(
    n_graphs: int = 900, epochs: int = EPOCHS, seed: int = RANDOM_SEED, verbose: bool = True
) -> Dict[str, Any]:
    """Train the GNN and return a serialisable checkpoint dict."""
    if not TORCH_AVAILABLE:
        raise RuntimeError(
            "PyTorch is required to train the GNN. Install it, or the platform "
            "will fall back to the analytic engine (reported as untrained)."
        )

    torch.manual_seed(seed)
    np.random.seed(seed % (2**32 - 1))

    graphs = generate_dataset(n_graphs=n_graphs, seed=seed)
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(graphs))
    split = int(len(graphs) * 0.8)
    train_graphs = [graphs[i] for i in order[:split]]
    test_graphs = [graphs[i] for i in order[split:]]

    summary = dataset_summary(graphs)
    if verbose:
        print(
            f"[gnn] dataset: {summary['graphs']} graphs, {summary['nodes']:,} nodes, "
            f"{summary['edges']:,} edges "
            f"(node positive rate {summary['node_positive_rate']:.1%})"
        )

    model = AmlGNN(
        node_dim=NODE_FEATURE_DIM,
        edge_dim=EDGE_FEATURE_DIM,
        hidden=HIDDEN_DIM,
        layers=NUM_LAYERS,
    )
    optimiser = torch.optim.AdamW(
        model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=epochs)

    # Positive-class weights counter the natural imbalance of flagged structures
    node_pos_weight = torch.tensor(
        max((1 - summary["node_positive_rate"]) / max(summary["node_positive_rate"], 1e-6), 1.0)
    ).clamp(max=6.0)
    edge_pos_weight = torch.tensor(
        max((1 - summary["edge_positive_rate"]) / max(summary["edge_positive_rate"], 1e-6), 1.0)
    ).clamp(max=8.0)

    node_criterion = nn.BCEWithLogitsLoss(pos_weight=node_pos_weight)
    edge_criterion = nn.BCEWithLogitsLoss(pos_weight=edge_pos_weight)
    graph_criterion = nn.BCEWithLogitsLoss()

    history: List[Dict[str, float]] = []

    for epoch in range(1, epochs + 1):
        model.train()
        epoch_order = rng.permutation(len(train_graphs))
        running_loss = 0.0
        optimiser.zero_grad()

        for step, gi in enumerate(epoch_order, start=1):
            graph = train_graphs[gi]
            x, edge_index, edge_attr, y_node, y_edge, y_graph = _to_tensors(graph)
            n_logits, e_logits, g_logit, _ = model(x, edge_index, edge_attr)

            loss = NODE_LOSS_WEIGHT * node_criterion(n_logits, y_node)
            if e_logits.numel():
                loss = loss + EDGE_LOSS_WEIGHT * edge_criterion(e_logits, y_edge)
            loss = loss + GRAPH_LOSS_WEIGHT * graph_criterion(
                g_logit.view(1), y_graph.view(1)
            )

            # Average across the accumulation window
            (loss / BATCH_GRAPHS).backward()
            running_loss += float(loss)

            if step % BATCH_GRAPHS == 0 or step == len(epoch_order):
                torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0)
                optimiser.step()
                optimiser.zero_grad()

        scheduler.step()
        avg_loss = running_loss / max(len(train_graphs), 1)
        history.append({"epoch": epoch, "loss": round(avg_loss, 5)})

        if verbose and (epoch % 5 == 0 or epoch == 1 or epoch == epochs):
            evaluation = _evaluate(model, test_graphs)
            print(
                f"[gnn] epoch {epoch:>3}/{epochs}  loss={avg_loss:.4f}  "
                f"node_f1={evaluation['node_classification']['f1']:.3f}  "
                f"edge_f1={evaluation['edge_scoring']['f1']:.3f}  "
                f"graph_acc={evaluation['subgraph_detection']['accuracy']:.3f}"
            )

    metrics = _evaluate(model, test_graphs)
    metrics["held_out_graphs"] = len(test_graphs)
    metrics["training_graphs"] = len(train_graphs)
    metrics["loss_history"] = history

    checkpoint: Dict[str, Any] = {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "architecture": ARCHITECTURE,
        "state_dict": model.state_dict(),
        "config": {
            "node_dim": NODE_FEATURE_DIM,
            "edge_dim": EDGE_FEATURE_DIM,
            "hidden": HIDDEN_DIM,
            "layers": NUM_LAYERS,
        },
        "hyperparameters": {
            "epochs": epochs,
            "learning_rate": LEARNING_RATE,
            "weight_decay": WEIGHT_DECAY,
            "optimiser": "AdamW",
            "scheduler": "CosineAnnealingLR",
            "batch_graphs": BATCH_GRAPHS,
            "hidden_dim": HIDDEN_DIM,
            "layers": NUM_LAYERS,
            "node_pos_weight": round(float(node_pos_weight), 3),
            "edge_pos_weight": round(float(edge_pos_weight), 3),
            "loss": "BCEWithLogits (node + edge + graph readout)",
        },
        "metrics": metrics,
        "dataset_summary": summary,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_data": TRAINING_DATA_DESCRIPTION,
        "notes": (
            "Genuinely trained by backpropagation on synthetic graphs whose "
            "laundering topologies are known by construction. Learns to recognise "
            "structural typologies, not criminality."
        ),
        "caveats": [
            "Trained on synthetic graphs; labels are structural ground truth, not "
            "confirmed laundering cases.",
            "Benign look-alike structures (flash-sale merchant collections, uniform "
            "contractor payout runs, same-day trade settlements) are included as hard "
            "negatives so the model cannot succeed by counting node degree alone. "
            "Every negative graph contains at least one such look-alike.",
            "READ THE NODE METRIC, NOT THE OTHER TWO. Edge scoring and subgraph "
            "detection both saturate near 1.0, and that is an artefact of how the "
            "labels were constructed rather than evidence of exceptional capability: "
            "an edge is labelled positive exactly when both its endpoints belong to an "
            "injected structure, which the endpoint embeddings already encode; and the "
            "graph label is 'contains at least one injected typology', which reduces to "
            "an OR over node predictions. Node classification (~0.95 F1) is the only "
            "one of the three that is genuinely discriminative on this dataset.",
            "Held-out metrics describe topology recognition on the same synthetic "
            "distribution and will not transfer directly to production data.",
            "Outputs are model-generated risk indicators for human triage. They are "
            "not evidence and do not establish that any offence occurred.",
        ],
    }

    if verbose:
        nc = metrics["node_classification"]
        ec = metrics["edge_scoring"]
        sd = metrics["subgraph_detection"]
        print(
            f"[gnn] held-out node: acc={nc['accuracy']} p={nc['precision']} "
            f"r={nc['recall']} f1={nc['f1']} auc={nc['roc_auc']}"
        )
        print(
            f"[gnn] held-out edge: acc={ec['accuracy']} p={ec['precision']} "
            f"r={ec['recall']} f1={ec['f1']} auc={ec['roc_auc']}"
        )
        print(
            f"[gnn] held-out subgraph: acc={sd['accuracy']} f1={sd['f1']} "
            f"auc={sd['roc_auc']}"
        )

    return checkpoint


def save_checkpoint(checkpoint: Dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(checkpoint, path)
    meta = {k: v for k, v in checkpoint.items() if k != "state_dict"}
    path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path


def train_and_save(
    path: Path, n_graphs: int = 900, epochs: int = EPOCHS, verbose: bool = True
) -> Path:
    checkpoint = train(n_graphs=n_graphs, epochs=epochs, verbose=verbose)
    return save_checkpoint(checkpoint, path)


if __name__ == "__main__":  # pragma: no cover
    from app.core.config import settings

    train_and_save(settings.gnn_model_abspath)
