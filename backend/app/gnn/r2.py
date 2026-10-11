"""R2: honest baselines for the reactive GNN on IBM AMLworld.

Question this answers: on independent data, at the real class balance, does
learned message passing over a transaction neighbourhood beat the same features
without the graph?

Models (all predict "did this account take part in laundering on this day"):

  seed-only      gradient boosting on the account's own window features
  seed+context   gradient boosting on the account's features plus hand-made
                 aggregates of its direct neighbours and its own transfers
                 (what a strong non-graph model can see)
  logistic       logistic regression on seed+context (a linear reference)
  gnn            the current directed GraphSAGE encoder (`AmlGNN`), retrained
                 on windows with a seed-node objective

Every model is fitted on the train split, its threshold is chosen on the
validation split, and it is scored once on the test split. Stochastic models
run over several seeds and report mean +- std.

Run (HI-Small: normal activity ends 2022-09-10, see app.datasets.amlworld):
    cd backend
    python -m app.gnn.r2 --trans ../data/amlworld/HI-Small_Trans.csv \\
                         --patterns ../data/amlworld/HI-Small_Patterns.txt \\
                         --until 2022-09-10
Add --quick for a fast pipeline check (few windows, 1 seed, 3 epochs).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.core.config import PROJECT_ROOT
from app.datasets import amlworld
from app.gnn import metrics
from app.gnn.window_dataset import DatasetConfig, WindowStore, build_or_load
from app.graph.features_v2 import AMLWORLD_SCHEMA, FeatureSchema, WindowConfig

logger = logging.getLogger("r2")

DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "amlworld"


@dataclass
class TrainConfig:
    epochs: int = 30
    patience: int = 5
    # No early stopping before this epoch: a run that warms up slowly must not
    # be cut off before it starts learning (validation PR-AUC is noisy early on)
    min_epochs: int = 10
    batch_windows: int = 64
    learning_rate: float = 3e-3
    weight_decay: float = 1e-4
    hidden: int = 64
    layers: int = 3
    dropout: float = 0.15
    # "auto" uses a CUDA GPU when PyTorch was installed with CUDA support
    device: str = "auto"


def resolve_device(name: str) -> str:
    import torch

    if name == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if name.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA requested but this PyTorch build has no GPU support (torch "
            f"{torch.__version__}); install a CUDA build or use --device cpu"
        )
    return name


@dataclass
class R2Config:
    transactions: Path
    patterns: Optional[Path] = None
    out_dir: Path = DEFAULT_DATA_DIR / "r2"
    until: Optional[date] = None
    dataset: DatasetConfig = field(default_factory=DatasetConfig)
    train: TrainConfig = field(default_factory=TrainConfig)
    seeds: int = 5
    schema: FeatureSchema = AMLWORLD_SCHEMA


# ---------------------------------------------------------------------------
# Non-graph baselines
# ---------------------------------------------------------------------------


def tabular_features(store: WindowStore, account_dim: int) -> Tuple[np.ndarray, np.ndarray]:
    """(seed-only, seed+context) feature matrices, one row per window.

    Context = mean and max of the direct neighbours' account features, plus mean
    and max of the seed's own transfers (in and out separately). No learning
    over the graph - just the aggregates an analyst-built model would use.
    """
    n = len(store)
    seed_only = store.seed_features()[:, :account_dim]
    edge_dim = store.edge_features.shape[1]
    context = np.zeros((n, 2 * account_dim + 4 * edge_dim + 2), dtype=np.float32)
    for i in range(n):
        w = store.window(i)
        src, dst = w["edge_index"]
        out_e, in_e = src == 0, dst == 0
        neighbours = np.unique(np.concatenate([dst[out_e], src[in_e]]))
        neighbours = neighbours[neighbours != 0]
        parts = []
        if neighbours.size:
            feats = w["x"][neighbours, :account_dim]
            parts += [feats.mean(0), feats.max(0)]
        else:
            parts += [np.zeros(account_dim), np.zeros(account_dim)]
        for mask in (out_e, in_e):
            e = w["edge_attr"][mask]
            parts += [e.mean(0), e.max(0)] if e.size else [np.zeros(edge_dim), np.zeros(edge_dim)]
        parts.append(np.asarray([out_e.sum(), in_e.sum()], dtype=np.float32) / 100.0)
        context[i] = np.concatenate(parts)
    return seed_only, np.hstack([seed_only, context])


def _fit_predict_tabular(kind: str, X_train, y_train, X_eval: List[np.ndarray], seed: int):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    if kind == "logistic":
        model = make_pipeline(
            StandardScaler(), LogisticRegression(max_iter=3000, class_weight="balanced")
        )
    else:
        model = HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.06, class_weight="balanced", random_state=seed,
            early_stopping=True, validation_fraction=0.15,
        )
    model.fit(X_train, y_train)
    return [model.predict_proba(X)[:, 1] for X in X_eval]


# ---------------------------------------------------------------------------
# GNN baseline: the current encoder, retrained on windows
# ---------------------------------------------------------------------------


def _collate(store: WindowStore, idx: np.ndarray, device: str = "cpu"):
    import torch

    xs, eis, eas, seeds = [], [], [], []
    offset = 0
    for i in idx:
        w = store.window(int(i))
        xs.append(w["x"])
        eis.append(w["edge_index"].astype(np.int64) + offset)
        eas.append(w["edge_attr"])
        seeds.append(offset)
        offset += w["x"].shape[0]
    tensors = (
        torch.from_numpy(np.concatenate(xs)),
        torch.from_numpy(np.concatenate(eis, axis=1) if eis else np.zeros((2, 0), np.int64)),
        torch.from_numpy(np.concatenate(eas)),
        torch.as_tensor(seeds, dtype=torch.long),
    )
    return tuple(t.to(device, non_blocking=True) for t in tensors)


def _score_gnn(model, store: WindowStore, batch: int) -> np.ndarray:
    import torch

    model.eval()
    device = next(model.parameters()).device
    out = []
    with torch.no_grad():
        for start in range(0, len(store), batch):
            idx = np.arange(start, min(start + batch, len(store)))
            x, ei, ea, seeds = _collate(store, idx, device)
            node_logits, _, _, _ = model(x, ei, ea)
            out.append(torch.sigmoid(node_logits[seeds]).cpu().numpy())
    return np.concatenate(out) if out else np.zeros(0)


def train_gnn(
    stores: Dict[str, WindowStore],
    schema: FeatureSchema,
    cfg: TrainConfig,
    seed: int,
    variant: str = "directed",
):
    """Train with early stopping on validation PR-AUC. Returns (model, history).

    `variant` picks the GraphSAGE flavour (see `app.gnn.sage`); "directed" is
    the original `AmlGNN`.
    """
    import torch
    import torch.nn as nn

    from app.gnn.sage import build_model

    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    torch.set_num_threads(max(1, min(8, (os.cpu_count() or 2) - 2)))
    device = resolve_device(cfg.device)

    train, val = stores["train"], stores["val"]
    model = build_model(
        variant, schema.node_dim, schema.edge_dim, cfg.hidden, cfg.layers, cfg.dropout
    ).to(device)
    optimiser = torch.optim.AdamW(model.parameters(), lr=cfg.learning_rate, weight_decay=cfg.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=cfg.epochs)
    pos = max(int(train.label.sum()), 1)
    criterion = nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor((len(train) - pos) / pos, device=device)
    )

    best_state, best_ap, stale, history = None, -1.0, 0, []
    for epoch in range(1, cfg.epochs + 1):
        model.train()
        order = rng.permutation(len(train))
        total = 0.0
        for start in range(0, len(order), cfg.batch_windows):
            idx = order[start : start + cfg.batch_windows]
            x, ei, ea, seeds = _collate(train, idx, device)
            node_logits, _, _, _ = model(x, ei, ea)
            y = torch.from_numpy(train.label[idx].astype(np.float32)).to(device)
            loss = criterion(node_logits[seeds], y)
            optimiser.zero_grad()
            loss.backward()
            optimiser.step()
            total += float(loss) * len(idx)
        scheduler.step()

        score = _score_gnn(model, val, cfg.batch_windows * 2)
        ap = metrics.evaluate(val.label, score, val.weight, 0.5)["pr_auc"] or 0.0
        history.append({"epoch": epoch, "loss": round(total / len(train), 5), "val_pr_auc": round(ap, 5)})
        logger.info(
            "gnn[%s] seed %d epoch %2d loss %.4f val PR-AUC %.4f (%s)",
            variant, seed, epoch, total / len(train), ap, device,
        )
        if ap > best_ap + 1e-4:
            best_ap, stale = ap, 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            stale += 1
            if stale >= cfg.patience and epoch >= cfg.min_epochs:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    return model, history


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _assess(name, val_score, test_score, stores, typology_names):
    val, test = stores["val"], stores["test"]
    threshold = metrics.best_threshold(val.label, val_score, val.weight)
    return {
        "model": name,
        "val": metrics.evaluate(val.label, val_score, val.weight, threshold),
        "test": metrics.evaluate(
            test.label, test_score, test.weight, threshold, test.typology, typology_names
        ),
    }


def data_name(config: R2Config) -> str:
    """Everything that changes the windows' content must change the cache key."""
    return ":".join(
        [config.transactions.name, config.patterns.name if config.patterns else "no-patterns",
         config.until.isoformat() if config.until else "all"]
    )


def prepare(config: R2Config):
    """Load the dataset and its (cached) windows. Returns (data, stores, splits)."""
    config.out_dir.mkdir(parents=True, exist_ok=True)
    data = amlworld.load(config.transactions, config.patterns, until=config.until)
    tail = data.tail_days()
    if tail:
        logger.warning(
            "low-volume tail days still included: %s - they inflate test scores; pass --until",
            ", ".join(tail),
        )
    stores, splits = build_or_load(
        data.source, data.is_laundering, data.typology, config.dataset, config.schema,
        config.out_dir, data_name(config),
    )
    for name in ("train", "val", "test"):
        if stores[name].label.sum() == 0:
            raise ValueError(f"the {name} split has no positive windows; use more data")
    return data, stores, splits


def save_checkpoint(path: Path, model, variant: str, config: R2Config, result, name: str) -> None:
    """A self-describing checkpoint: weights, architecture, schema, window, threshold."""
    import torch

    schema = config.schema
    torch.save(
        {
            "model_name": name,
            "variant": variant,
            # Saved on the CPU so the checkpoint loads on machines without a GPU
            "state_dict": {k: v.cpu() for k, v in model.state_dict().items()},
            "config": {"node_dim": schema.node_dim, "edge_dim": schema.edge_dim,
                       "hidden": config.train.hidden, "layers": config.train.layers},
            "schema": schema.to_dict(),
            "window": asdict(config.dataset.window),
            "threshold": result["val"]["threshold"],
            "metrics": {"val": result["val"], "test": result["test"]},
            "training_data": f"IBM AMLworld {config.transactions.name}"
            + (f" up to {config.until.isoformat()}" if config.until else ""),
        },
        path,
    )


def run(config: R2Config) -> Dict[str, object]:
    started = time.perf_counter()
    data, stores, splits = prepare(config)

    schema = config.schema
    names = data.typology_names
    tab = {k: tabular_features(stores[k], schema.account_dim) for k in ("train", "val", "test")}
    results: Dict[str, List[Dict[str, object]]] = {}

    for kind, view, seeds in (
        ("seed-only", 0, config.seeds),
        ("seed+context", 1, config.seeds),
        ("logistic", 1, 1),
    ):
        runs = []
        for s in range(seeds):
            label = "logistic" if kind == "logistic" else "hgb"
            val_s, test_s = _fit_predict_tabular(
                label, tab["train"][view], stores["train"].label,
                [tab["val"][view], tab["test"][view]], seed=s,
            )
            runs.append(_assess(kind, val_s, test_s, stores, names))
        results[kind] = runs
        logger.info("%s test PR-AUC %s", kind, [round(r["test"]["pr_auc"] or 0, 4) for r in runs])

    gnn_runs, best = [], None
    for s in range(config.seeds):
        model, history = train_gnn(stores, schema, config.train, seed=s)
        batch = config.train.batch_windows * 2
        result = _assess("gnn", _score_gnn(model, stores["val"], batch), _score_gnn(model, stores["test"], batch), stores, names)
        result["history"] = history
        gnn_runs.append(result)
        if best is None or result["val"]["pr_auc"] > best[0]["val"]["pr_auc"]:
            best = (result, model)
    results["gnn"] = gnn_runs

    report = {
        "stage": "R2",
        "dataset": data.summary(),
        "splits": [
            {**{k: v for k, v in asdict(s).items()}, "days": len(s.anchors)} for s in splits
        ],
        "windows": {k: stores[k].meta.get("build", {}) | {"count": len(stores[k]), "positives": int(stores[k].label.sum())} for k in stores},
        "config": {
            "dataset": asdict(config.dataset),
            "train": asdict(config.train),
            "schema": schema.to_dict(),
            "seeds": config.seeds,
        },
        "results": {
            name: {
                "val": metrics.summarise([r["val"] for r in runs]),
                "test": metrics.summarise([r["test"] for r in runs]),
            }
            for name, runs in results.items()
        },
        "seconds": round(time.perf_counter() - started, 1),
    }

    best_result, best_model = best
    tag = config.dataset.fingerprint(schema, data_name(config))
    save_checkpoint(
        config.out_dir / f"r2_gnn_baseline-{tag}.pt", best_model, "directed", config,
        best_result, "aml_gnn_r2_baseline",
    )
    path = config.out_dir / f"r2_report-{tag}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    report["report_path"] = str(path)
    return report


def format_table(report: Dict[str, object]) -> str:
    def cell(stat):
        if not isinstance(stat, dict) or "mean" not in stat:
            return "      -      "
        return f"{stat['mean']:.3f} +- {stat['std']:.3f}"

    lines = [
        "model          test PR-AUC      test F1          precision        recall           alert rate",
    ]
    for name, res in report["results"].items():
        t = res["test"]
        lines.append(
            f"{name:<14} {cell(t.get('pr_auc'))}  {cell(t.get('f1'))}  {cell(t.get('precision'))}  "
            f"{cell(t.get('recall'))}  {cell(t.get('alert_rate'))}"
        )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="R2 baselines on IBM AMLworld")
    parser.add_argument("--trans", type=Path, required=True, help="<VARIANT>_Trans.csv")
    parser.add_argument("--patterns", type=Path, help="<VARIANT>_Patterns.txt (typology labels)")
    parser.add_argument("--out", type=Path, default=DEFAULT_DATA_DIR / "r2")
    parser.add_argument("--until", type=date.fromisoformat,
                        help="last UTC day to keep, YYYY-MM-DD (HI-Small: 2022-09-10)")
    parser.add_argument("--quick", action="store_true",
                        help="pipeline check: <=50 positives/day, 0.2%% negatives, 1 seed, 3 epochs")
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--device", default="auto", help="auto | cpu | cuda (GNN training only)")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--hops", type=int, default=3)
    parser.add_argument("--max-nodes", type=int, default=300)
    parser.add_argument("--neg-rate-train", type=float, default=0.01)
    parser.add_argument("--neg-rate-eval", type=float, default=0.02)
    parser.add_argument("--max-pos-per-day", type=int)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    if args.quick:
        args.seeds, args.epochs = 1, 3
        args.max_pos_per_day = args.max_pos_per_day or 50
        args.neg_rate_train = args.neg_rate_eval = 0.002
    config = R2Config(
        transactions=args.trans,
        patterns=args.patterns,
        out_dir=args.out / "quick" if args.quick else args.out,
        until=args.until,
        seeds=args.seeds,
        dataset=DatasetConfig(
            window=WindowConfig(days=args.days, hops=args.hops, max_nodes=args.max_nodes),
            neg_rate_train=args.neg_rate_train,
            neg_rate_eval=args.neg_rate_eval,
            max_pos_per_day=args.max_pos_per_day,
        ),
        train=replace(TrainConfig(), epochs=args.epochs, device=args.device),
    )
    report = run(config)
    print(format_table(report))
    print(f"\nreport: {report['report_path']}")


if __name__ == "__main__":
    main()
