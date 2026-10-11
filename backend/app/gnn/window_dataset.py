"""Turns a labelled transfer dataset into GNN training windows.

Protocol
--------
* Temporal split. Transfers are cut 60/20/20 by count in time order, with the
  cut moved to the nearest preceding UTC midnight, so every model is trained on
  the past and tested on the future. Windows of later splits may look back into
  earlier periods for context (that history exists at inference time too), but
  labels only ever come from the split's own days.
* One anchor per day. A window ends at UTC midnight and is centred on an account
  ("the seed") active during the preceding day. This is the batch form of what
  the live pipeline does when a transfer settles.
* Seed label = the seed sent or received a laundering transfer that day.
* Sampling. Every positive seed is kept. Negatives are sampled at a fixed rate
  and carry weight 1/rate, so precision, PR-AUC and alert rates computed with
  those weights are unbiased estimates for "every active account" - the class
  balance the system really faces - without building millions of windows.

Windows are written to a compact store (concatenated arrays + offsets, one
`.npz` per split) so experiments rerun without rebuilding them.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from app.graph.columnar_source import ColumnarTransferSource
from app.graph.features_v2 import FeatureSchema, WindowConfig
from app.graph.window import WindowCache, build_window

logger = logging.getLogger(__name__)

DAY = timedelta(days=1)
SPLITS = ("train", "val", "test")


@dataclass(frozen=True)
class DatasetConfig:
    window: WindowConfig = WindowConfig()
    fractions: Tuple[float, float, float] = (0.6, 0.2, 0.2)
    neg_rate_train: float = 0.01
    neg_rate_eval: float = 0.02
    max_pos_per_day: Optional[int] = None  # cap for quick runs; None keeps all
    random_seed: int = 7

    def fingerprint(self, schema: FeatureSchema, data_name: str) -> str:
        payload = json.dumps(
            {"config": asdict(self), "schema": schema.to_dict(), "data": data_name},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha1(payload.encode()).hexdigest()[:12]


@dataclass
class TemporalSplit:
    name: str
    start: datetime  # exclusive
    end: datetime  # inclusive
    transfers: int = 0
    laundering: int = 0

    @property
    def anchors(self) -> List[datetime]:
        out, t = [], self.start + DAY
        while t <= self.end:
            out.append(t)
            t += DAY
        return out


def _midnight(t: datetime) -> datetime:
    return t.replace(hour=0, minute=0, second=0, microsecond=0)


def temporal_splits(
    source: ColumnarTransferSource,
    is_laundering: np.ndarray,
    fractions: Tuple[float, float, float] = (0.6, 0.2, 0.2),
) -> List[TemporalSplit]:
    """Day-aligned train / val / test periods covering the whole dataset."""
    times = source._sorted_time
    n = len(times)
    first, last = source.time_range
    # Periods are (start, end]; a transfer at exactly midnight belongs to the day before
    second = timedelta(seconds=1)
    lo = _midnight(first - second)
    hi = _midnight(last - second) + DAY
    cuts = []
    for frac in np.cumsum(fractions)[:-1]:
        t = datetime.fromtimestamp(int(times[min(int(n * frac), n - 1)]), tz=timezone.utc)
        cuts.append(_midnight(t))
    bounds = [lo, *cuts, hi]
    splits = []
    for name, start, end in zip(SPLITS, bounds[:-1], bounds[1:]):
        idx = source.transfers_between(start, end)
        splits.append(
            TemporalSplit(
                name=name,
                start=start,
                end=end,
                transfers=int(idx.size),
                laundering=int(is_laundering[idx].sum()),
            )
        )
    if any(s.end <= s.start for s in splits):
        raise ValueError(f"degenerate temporal split {[(s.name, s.start, s.end) for s in splits]}")
    return splits


# ---------------------------------------------------------------------------
# Window store
# ---------------------------------------------------------------------------


@dataclass
class WindowStore:
    """Many windows in concatenated arrays. Window i owns node rows
    `node_ptr[i]:node_ptr[i+1]` and edge rows `edge_ptr[i]:edge_ptr[i+1]`;
    edge indices are local to their window. The seed is each window's row 0."""

    node_features: np.ndarray
    edge_index: np.ndarray  # (2, E_total) int32, local
    edge_features: np.ndarray
    edge_label: np.ndarray  # bool: the transfer is labelled laundering
    edge_in_target_day: np.ndarray  # bool: the transfer happened on the anchor day
    node_ptr: np.ndarray
    edge_ptr: np.ndarray
    label: np.ndarray  # int8 seed label
    weight: np.ndarray  # float32 inverse sampling probability
    typology: np.ndarray  # int16 seed typology code (0 = none / unlisted)
    anchor: np.ndarray  # int64 epoch seconds
    seed_keys: List[str]
    truncated: np.ndarray  # bool
    meta: Dict[str, object] = field(default_factory=dict)

    def __len__(self) -> int:
        return int(self.label.shape[0])

    def window(self, i: int) -> Dict[str, np.ndarray]:
        a, b = self.node_ptr[i], self.node_ptr[i + 1]
        c, d = self.edge_ptr[i], self.edge_ptr[i + 1]
        return {
            "x": self.node_features[a:b],
            "edge_index": self.edge_index[:, c:d],
            "edge_attr": self.edge_features[c:d],
            "edge_label": self.edge_label[c:d],
            "edge_in_target_day": self.edge_in_target_day[c:d],
        }

    def seed_features(self) -> np.ndarray:
        return self.node_features[self.node_ptr[:-1]]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            path,
            node_features=self.node_features,
            edge_index=self.edge_index,
            edge_features=self.edge_features,
            edge_label=self.edge_label,
            edge_in_target_day=self.edge_in_target_day,
            node_ptr=self.node_ptr,
            edge_ptr=self.edge_ptr,
            label=self.label,
            weight=self.weight,
            typology=self.typology,
            anchor=self.anchor,
            seed_keys=np.asarray(self.seed_keys),
            truncated=self.truncated,
            meta=np.asarray(json.dumps(self.meta, default=str)),
        )

    @classmethod
    def load(cls, path: Path) -> "WindowStore":
        with np.load(path, allow_pickle=False) as data:
            fields = {k: data[k] for k in data.files}
        meta = json.loads(str(fields.pop("meta")))
        seed_keys = [str(k) for k in fields.pop("seed_keys")]
        return cls(seed_keys=seed_keys, meta=meta, **fields)


class _StoreBuilder:
    def __init__(self, node_dim: int, edge_dim: int):
        self.node_dim, self.edge_dim = node_dim, edge_dim
        self.x: List[np.ndarray] = []
        self.ei: List[np.ndarray] = []
        self.ea: List[np.ndarray] = []
        self.el: List[np.ndarray] = []
        self.et: List[np.ndarray] = []
        self.n_nodes: List[int] = []
        self.n_edges: List[int] = []
        self.rows: Dict[str, list] = {k: [] for k in ("label", "weight", "typology", "anchor", "seed", "truncated")}

    def add(self, window, edge_label, edge_in_target, label, weight, typology, anchor) -> None:
        self.x.append(window.node_features)
        self.ei.append(window.edge_index.astype(np.int32))
        self.ea.append(window.edge_features)
        self.el.append(edge_label)
        self.et.append(edge_in_target)
        self.n_nodes.append(window.num_nodes)
        self.n_edges.append(window.num_edges)
        self.rows["label"].append(label)
        self.rows["weight"].append(weight)
        self.rows["typology"].append(typology)
        self.rows["anchor"].append(anchor)
        self.rows["seed"].append(window.seed)
        self.rows["truncated"].append(window.truncated_nodes or window.truncated_edges)

    def build(self, meta: Dict[str, object]) -> WindowStore:
        def cat(parts, width, dtype):
            return np.concatenate(parts).astype(dtype) if parts else np.zeros((0, width), dtype)

        return WindowStore(
            node_features=cat(self.x, self.node_dim, np.float32),
            edge_index=(
                np.concatenate(self.ei, axis=1) if self.ei else np.zeros((2, 0), np.int32)
            ),
            edge_features=cat(self.ea, self.edge_dim, np.float32),
            edge_label=np.concatenate(self.el).astype(bool) if self.el else np.zeros(0, bool),
            edge_in_target_day=np.concatenate(self.et).astype(bool) if self.et else np.zeros(0, bool),
            node_ptr=np.concatenate([[0], np.cumsum(self.n_nodes)]).astype(np.int64),
            edge_ptr=np.concatenate([[0], np.cumsum(self.n_edges)]).astype(np.int64),
            label=np.asarray(self.rows["label"], dtype=np.int8),
            weight=np.asarray(self.rows["weight"], dtype=np.float32),
            typology=np.asarray(self.rows["typology"], dtype=np.int16),
            anchor=np.asarray(self.rows["anchor"], dtype=np.int64),
            seed_keys=list(self.rows["seed"]),
            truncated=np.asarray(self.rows["truncated"], dtype=bool),
            meta=meta,
        )


def build_split_windows(
    source: ColumnarTransferSource,
    is_laundering: np.ndarray,
    typology: np.ndarray,
    split: TemporalSplit,
    config: DatasetConfig,
    schema: FeatureSchema,
) -> WindowStore:
    """Sample seeds for each day of `split` and build their windows."""
    rng = np.random.default_rng([config.random_seed, SPLITS.index(split.name)])
    neg_rate = config.neg_rate_train if split.name == "train" else config.neg_rate_eval
    cols = source.columns
    out = _StoreBuilder(schema.node_dim, schema.edge_dim)
    started = time.perf_counter()
    stats = {"days": 0, "active": 0, "positives": 0, "negatives": 0, "truncated": 0}

    for anchor in split.anchors:
        day = source.transfers_between(anchor - DAY, anchor)
        if day.size == 0:
            continue
        active = np.unique(np.concatenate([cols.source[day], cols.target[day]]))
        bad = day[is_laundering[day]]
        pos_typ: Dict[int, int] = {}
        for i in bad:
            for account in (int(cols.source[i]), int(cols.target[i])):
                pos_typ.setdefault(account, int(typology[i]))
                if pos_typ[account] == 0 and typology[i] != 0:
                    pos_typ[account] = int(typology[i])
        positives = np.asarray(sorted(pos_typ), dtype=np.int64)
        pos_weight = 1.0
        if config.max_pos_per_day is not None and positives.size > config.max_pos_per_day:
            pos_weight = positives.size / config.max_pos_per_day
            positives = np.sort(rng.choice(positives, config.max_pos_per_day, replace=False))
        negatives_pool = np.setdiff1d(active, np.asarray(sorted(pos_typ), dtype=np.int64))
        negatives = negatives_pool[rng.random(negatives_pool.size) < neg_rate]

        cache = WindowCache()
        day_lo, day_hi = (anchor - DAY).timestamp(), anchor.timestamp()
        for account, label in [(int(a), 1) for a in positives] + [(int(a), 0) for a in negatives]:
            window = build_window(source, cols.account_keys[account], anchor, config.window, schema, cache)
            ids = np.fromiter((t.db_id for t in window.transfers), dtype=np.int64, count=window.num_edges)
            when = cols.time[ids] if ids.size else np.zeros(0, np.int64)
            out.add(
                window,
                edge_label=is_laundering[ids] if ids.size else np.zeros(0, bool),
                edge_in_target=(when > day_lo) & (when <= day_hi),
                label=label,
                weight=pos_weight if label else 1.0 / neg_rate,
                typology=pos_typ.get(account, 0) if label else 0,
                anchor=int(anchor.timestamp()),
            )
            stats["truncated"] += int(window.truncated_nodes or window.truncated_edges)
        stats["days"] += 1
        stats["active"] += int(active.size)
        stats["positives"] += int(positives.size)
        stats["negatives"] += int(negatives.size)
        logger.info(
            "%s %s: %d active, %d positive, %d negative windows (%.0fs elapsed)",
            split.name, anchor.date(), active.size, positives.size, negatives.size,
            time.perf_counter() - started,
        )

    stats["seconds"] = round(time.perf_counter() - started, 1)
    stats["neg_rate"] = neg_rate
    return out.build(
        {
            "split": split.name,
            "start": split.start.isoformat(),
            "end": split.end.isoformat(),
            "schema": schema.to_dict(),
            "window": asdict(config.window),
            "build": stats,
        }
    )


def window_cache_folder(
    config: DatasetConfig, schema: FeatureSchema, cache_dir: Path, data_name: str
) -> Path:
    """Where the windows for this exact configuration are (or will be) cached."""
    return Path(cache_dir) / f"windows-{config.fingerprint(schema, data_name)}"


def build_or_load(
    source: ColumnarTransferSource,
    is_laundering: np.ndarray,
    typology: np.ndarray,
    config: DatasetConfig,
    schema: FeatureSchema,
    cache_dir: Path,
    data_name: str,
) -> Tuple[Dict[str, WindowStore], List[TemporalSplit]]:
    """Windows for every split, from `cache_dir` when an identical build exists."""
    splits = temporal_splits(source, is_laundering, config.fractions)
    folder = window_cache_folder(config, schema, cache_dir, data_name)
    stores: Dict[str, WindowStore] = {}
    for split in splits:
        path = folder / f"{split.name}.npz"
        if path.exists():
            stores[split.name] = WindowStore.load(path)
            logger.info("loaded %d %s windows from %s", len(stores[split.name]), split.name, path)
            continue
        store = build_split_windows(source, is_laundering, typology, split, config, schema)
        store.save(path)
        stores[split.name] = store
    return stores, splits
