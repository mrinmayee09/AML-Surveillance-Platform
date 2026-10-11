"""R3: GraphSAGE ablation on IBM AMLworld.

Adds one idea at a time and measures each, on exactly the R2 windows, seeds,
thresholding and test protocol:

  A  plain     GraphSAGE ignoring direction and amounts
  B  directed  incoming / outgoing handled separately, amount-weighted (R2's GNN)
  C  edge      B + transfer details inside every message

B's numbers are taken from the R2 report when one exists for the same windows
(it is the same model, code path and seeds); otherwise B is trained here too.

The model the app will use is the variant with the best MEAN VALIDATION PR-AUC.
The test split never influences that choice. Its best-validation seed is
exported to `app/gnn/artifacts/aml_gnn_v2.pt` with a `.meta.json` sidecar.

Run:
    cd backend
    python -m app.gnn.r3 --trans ../data/amlworld/HI-Small_Trans.csv \\
                         --patterns ../data/amlworld/HI-Small_Patterns.txt \\
                         --until 2022-09-10
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import time
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from app.gnn import metrics, r2
from app.gnn.sage import VARIANTS, build_model, count_parameters
from app.gnn.v2_model import EXPORT_PATH
from app.gnn.window_dataset import DatasetConfig
from app.graph.features_v2 import WindowConfig

logger = logging.getLogger("r3")

LABELS = {"plain": "A plain GraphSAGE", "directed": "B directed GraphSAGE", "edge": "C edge-aware GraphSAGE"}


def _r2_report(config: r2.R2Config) -> Optional[dict]:
    tag = config.dataset.fingerprint(config.schema, r2.data_name(config))
    path = config.out_dir / f"r2_report-{tag}.json"
    if not path.exists():
        return None
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("config", {}).get("seeds") != config.seeds:
        logger.warning("R2 report used %s seeds, R3 uses %s - retraining B here",
                       report.get("config", {}).get("seeds"), config.seeds)
        return None
    return report


def run(config: r2.R2Config, variants=VARIANTS, export: bool = True) -> Dict[str, object]:
    started = time.perf_counter()
    data, stores, splits = r2.prepare(config)
    names = data.typology_names
    dataset_summary = data.summary()
    del data  # the windows are all R3 needs; free the ~2 GB transfer columns

    tag = config.dataset.fingerprint(config.schema, r2.data_name(config))
    previous = _r2_report(config)
    results: Dict[str, Dict[str, object]] = {}
    if previous:
        for name in ("seed-only", "seed+context", "logistic"):
            results[name] = previous["results"][name]

    batch = config.train.batch_windows * 2
    checkpoints: Dict[str, Path] = {}
    timing: Dict[str, float] = {}
    params: Dict[str, int] = {}

    for variant in variants:
        params[variant] = count_parameters(
            build_model(variant, config.schema.node_dim, config.schema.edge_dim,
                        config.train.hidden, config.train.layers, config.train.dropout)
        )
        if variant == "directed" and previous and "gnn" in previous["results"]:
            results[variant] = previous["results"]["gnn"]
            checkpoints[variant] = config.out_dir / f"r2_gnn_baseline-{tag}.pt"
            logger.info("B (directed) taken from the R2 report")
            continue

        t0 = time.perf_counter()
        runs, best = [], None
        for seed in range(config.seeds):
            model, history = r2.train_gnn(stores, config.schema, config.train, seed, variant)
            result = r2._assess(
                variant, r2._score_gnn(model, stores["val"], batch),
                r2._score_gnn(model, stores["test"], batch), stores, names,
            )
            result["history"] = history
            runs.append(result)
            if best is None or result["val"]["pr_auc"] > best[0]["val"]["pr_auc"]:
                best = (result, model)
            logger.info("%s seed %d: val PR-AUC %.4f, test PR-AUC %.4f", variant, seed,
                        result["val"]["pr_auc"], result["test"]["pr_auc"])
        timing[variant] = round(time.perf_counter() - t0, 1)
        results[variant] = {
            "val": metrics.summarise([r["val"] for r in runs]),
            "test": metrics.summarise([r["test"] for r in runs]),
            "epochs_run": [len(r["history"]) for r in runs],
        }
        path = config.out_dir / f"r3_gnn_{variant}-{tag}.pt"
        r2.save_checkpoint(path, best[1], variant, config, best[0], f"aml_gnn_{variant}")
        checkpoints[variant] = path

    # Model selection on validation only
    chosen = max(variants, key=lambda v: results[v]["val"]["pr_auc"]["mean"])
    report = {
        "stage": "R3",
        "dataset": dataset_summary,
        "splits": [{**asdict(s), "days": len(s.anchors)} for s in splits],
        "config": {
            "dataset": asdict(config.dataset),
            "train": asdict(config.train),
            "schema": config.schema.to_dict(),
            "seeds": config.seeds,
        },
        "variants": {v: {"label": LABELS[v], "parameters": params[v], "seconds": timing.get(v)} for v in variants},
        "results": results,
        "selected": {
            "variant": chosen,
            "rule": "highest mean validation PR-AUC across seeds; test split not used",
            "checkpoint": str(checkpoints[chosen]),
        },
        "seconds": round(time.perf_counter() - started, 1),
    }
    out = config.out_dir / f"r3_report-{tag}.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    report["report_path"] = str(out)

    if export:
        export_model(checkpoints[chosen], report)
    return report


def export_model(checkpoint: Path, report: Dict[str, object], target: Path = EXPORT_PATH) -> Path:
    """Copy the selected checkpoint to where the app loads it, plus a readable sidecar."""
    import torch

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(checkpoint, target)
    ckpt = torch.load(target, map_location="cpu", weights_only=False)
    meta = {k: v for k, v in ckpt.items() if k != "state_dict"}
    meta["selection"] = report["selected"]
    meta["ablation"] = {
        name: {"test_pr_auc": res["test"].get("pr_auc"), "val_pr_auc": res["val"].get("pr_auc")}
        for name, res in report["results"].items()
    }
    target.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    logger.info("exported %s -> %s", checkpoint.name, target)
    return target


def format_table(report: Dict[str, object]) -> str:
    def cell(stat):
        if not isinstance(stat, dict) or "mean" not in stat:
            return "      -       "
        return f"{stat['mean']:.3f} +- {stat['std']:.3f}"

    rows = ["model                     test PR-AUC      F1               precision        recall           val PR-AUC"]
    for name, res in report["results"].items():
        t, v = res["test"], res["val"]
        label = LABELS.get(name, name)
        rows.append(f"{label:<25} {cell(t.get('pr_auc'))}  {cell(t.get('f1'))}  {cell(t.get('precision'))}  "
                    f"{cell(t.get('recall'))}  {cell(v.get('pr_auc'))}")
    rows.append(f"\nselected for the app: {LABELS[report['selected']['variant']]} ({report['selected']['rule']})")
    return "\n".join(rows)


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="R3 GraphSAGE ablation on IBM AMLworld")
    parser.add_argument("--trans", type=Path, required=True)
    parser.add_argument("--patterns", type=Path)
    parser.add_argument("--out", type=Path, default=r2.DEFAULT_DATA_DIR / "r2")
    parser.add_argument("--until", type=date.fromisoformat)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--variants", nargs="+", default=list(VARIANTS), choices=list(VARIANTS))
    parser.add_argument("--no-export", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    config = r2.R2Config(
        transactions=args.trans,
        patterns=args.patterns,
        out_dir=args.out,
        until=args.until,
        seeds=args.seeds,
        dataset=DatasetConfig(window=WindowConfig()),
        train=replace(r2.TrainConfig(), epochs=args.epochs, device=args.device),
    )
    report = run(config, variants=tuple(args.variants), export=not args.no_export)
    print(format_table(report))
    print(f"\nreport: {report['report_path']}")


if __name__ == "__main__":
    main()
