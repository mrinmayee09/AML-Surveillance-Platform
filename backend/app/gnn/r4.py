"""R4: are the GNN's explanations faithful?

For accounts the selected model flags on the TEST split, delete the top-k
transfers its explanation names and compare the score drop with deleting k
random transfers from the same candidate set. If explanations point at what the
model really uses, the top-k drop is clearly larger and flips more flags.

Run (after R3 has exported the model):
    cd backend
    python -m app.gnn.r4 --trans ../data/amlworld/HI-Small_Trans.csv \\
                         --patterns ../data/amlworld/HI-Small_Patterns.txt \\
                         --until 2022-09-10
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from app.gnn import r2
from app.gnn.explain_v2 import deletion_test
from app.gnn.v2_model import EXPORT_PATH, LoadedModel, load_checkpoint
from app.gnn.window_dataset import DatasetConfig, WindowStore, window_cache_folder
from app.graph.features_v2 import WindowConfig

logger = logging.getLogger("r4")


def fidelity(loaded: LoadedModel, store: WindowStore, k: int = 3, max_windows: int = 300,
             seed: int = 0) -> Dict[str, object]:
    started = time.perf_counter()
    scores = r2._score_gnn(loaded.model, store, 128)
    flagged = np.flatnonzero(scores >= loaded.threshold)
    rng = np.random.default_rng(seed)
    sample = np.sort(rng.choice(flagged, size=min(max_windows, flagged.size), replace=False))

    rows: List[Dict[str, float]] = []
    for i in sample:
        w = store.window(int(i))
        out = deletion_test(loaded.model, w["x"], w["edge_index"], w["edge_attr"], k=k, rng=rng)
        if out is not None:
            out["label"] = int(store.label[i])
            rows.append(out)

    def summary(subset: List[Dict[str, float]]) -> Dict[str, float]:
        if not subset:
            return {"windows": 0}
        top = np.asarray([r["top_k_drop"] for r in subset])
        rnd = np.asarray([r["random_k_drop"] for r in subset])
        base = np.asarray([r["base"] for r in subset])
        return {
            "windows": len(subset),
            "mean_score": float(base.mean()),
            "mean_top_k_drop": float(top.mean()),
            "mean_random_k_drop": float(rnd.mean()),
            "top_beats_random": float((top > rnd).mean()),
            # Removing the explained transfers un-flags the account
            "top_k_flip_rate": float(((base - top) < loaded.threshold).mean()),
            "random_k_flip_rate": float(((base - rnd) < loaded.threshold).mean()),
        }

    return {
        "k": k,
        "model": {"variant": loaded.variant, "threshold": loaded.threshold, "path": loaded.path},
        "flagged_test_windows": int(flagged.size),
        "all_flagged": summary(rows),
        "true_positives_only": summary([r for r in rows if r["label"] == 1]),
        "seconds": round(time.perf_counter() - started, 1),
    }


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="R4 explanation fidelity on the AMLworld test split")
    parser.add_argument("--trans", type=Path, required=True)
    parser.add_argument("--patterns", type=Path)
    parser.add_argument("--out", type=Path, default=r2.DEFAULT_DATA_DIR / "r2")
    parser.add_argument("--until", type=date.fromisoformat)
    parser.add_argument("--model", type=Path, default=EXPORT_PATH)
    parser.add_argument("--k", type=int, nargs="+", default=[3, 5])
    parser.add_argument("--max-windows", type=int, default=300)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    config = r2.R2Config(transactions=args.trans, patterns=args.patterns, out_dir=args.out,
                         until=args.until, dataset=DatasetConfig(window=WindowConfig()))
    folder = window_cache_folder(config.dataset, config.schema, config.out_dir, r2.data_name(config))
    store = WindowStore.load(folder / "test.npz")
    loaded = load_checkpoint(args.model)

    report = {"stage": "R4", "results": {f"k={k}": fidelity(loaded, store, k, args.max_windows) for k in args.k}}
    tag = folder.name.replace("windows-", "")
    path = config.out_dir / f"r4_report-{tag}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for name, res in report["results"].items():
        a = res["all_flagged"]
        print(f"{name}: {a.get('windows')} flagged test accounts | score drop top-k {a.get('mean_top_k_drop', 0):.3f} "
              f"vs random {a.get('mean_random_k_drop', 0):.3f} | top beats random {a.get('top_beats_random', 0):.0%} "
              f"| un-flags {a.get('top_k_flip_rate', 0):.0%} vs {a.get('random_k_flip_rate', 0):.0%}")
    print(f"\nreport: {path}")


if __name__ == "__main__":
    main()
