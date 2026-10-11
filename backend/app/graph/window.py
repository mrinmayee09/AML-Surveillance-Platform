"""Neighbourhood windows: the unit the reactive GNN is trained and scored on.

A window is every account within `hops` of a seed account, over the `days`
before `window_end`, capped at `max_nodes` / `max_edges`. The SAME builder runs
over every source:

  * `app.graph.columnar_source.ColumnarTransferSource` - IBM AMLworld (training)
  * `app.graph.db_source.DbTransferSource` - the live database
  * `InMemoryTransferSource` - tests and small fixtures

so a training sample and a live neighbourhood are produced by identical code.

Node features come from each account's activity across the whole source inside
the window (see `features_v2`), so an account looks the same in every window
that shares its `window_end`, whichever account the window is centred on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Protocol, Sequence, Set

import numpy as np

from app.db.types import as_utc
from app.graph.features_v2 import (
    PLATFORM_SCHEMA,
    AccountProfile,
    AccountWindowStats,
    FeatureSchema,
    TransferRecord,
    WindowConfig,
    as_matrix,
    compute_account_stats,
    edge_feature_vector,
    in_window,
    node_feature_vector,
)


class TransferSource(Protocol):
    """Where transfers and account profiles come from."""

    def fetch_touching(
        self, keys: Sequence[str], start: datetime, end: datetime
    ) -> List[TransferRecord]:
        """Every settled transfer in (start, end] with `keys` as sender or receiver."""

    def profiles(self, keys: Sequence[str]) -> Dict[str, AccountProfile]:
        """Profiles for `keys`; unknown keys may be omitted (a default is used)."""


@dataclass
class NeighbourhoodWindow:
    """A featurised neighbourhood, ready for the GNN."""

    seed: str
    window_start: datetime
    window_end: datetime
    config: WindowConfig
    node_keys: List[str]  # seed is always index 0
    node_hops: Dict[str, int]
    node_features: np.ndarray  # (N, schema.node_dim)
    edge_keys: List[str]
    edge_index: np.ndarray  # (2, E) int64: row 0 source idx, row 1 target idx
    edge_features: np.ndarray  # (E, schema.edge_dim)
    # Minutes before window_end, per edge - raw time for time-ordered aggregation
    edge_minutes_before_end: np.ndarray  # (E,)
    stats: Dict[str, AccountWindowStats] = field(repr=False)
    profiles: Dict[str, AccountProfile] = field(repr=False)
    transfers: List[TransferRecord] = field(repr=False)
    truncated_nodes: bool = False
    truncated_edges: bool = False
    hubs_not_expanded: List[str] = field(default_factory=list)
    schema: FeatureSchema = PLATFORM_SCHEMA

    @property
    def num_nodes(self) -> int:
        return len(self.node_keys)

    @property
    def num_edges(self) -> int:
        return len(self.edge_keys)

    @property
    def seed_index(self) -> int:
        return 0


class WindowCache:
    """Per-account transfer lists and stats shared by windows with one (start, end).

    Building many windows for the same window end (e.g. every sampled account on
    one day) touches the same accounts over and over; the cache makes each one
    cost a single fetch and a single stats computation. A cache bound to another
    window or schema resets itself, so reuse can never mix windows.
    """

    def __init__(self) -> None:
        self._bound: Optional[tuple] = None
        self.touching: Dict[str, List[TransferRecord]] = {}
        self.stats: Dict[str, AccountWindowStats] = {}
        self.profiles: Dict[str, AccountProfile] = {}

    def bind(self, start: datetime, end: datetime, schema: FeatureSchema) -> None:
        key = (start, end, schema)
        if self._bound != key:
            self._bound = key
            self.touching.clear()
            self.stats.clear()
            self.profiles.clear()


def build_window(
    source: TransferSource,
    seed: str,
    window_end: datetime,
    config: WindowConfig = WindowConfig(),
    schema: FeatureSchema = PLATFORM_SCHEMA,
    cache: Optional[WindowCache] = None,
) -> NeighbourhoodWindow:
    """Build the neighbourhood window around `seed` ending at `window_end`.

    Deterministic: the same source, seed and end always give the same window,
    including which accounts are kept when the caps bite. A `cache` changes the
    cost, never the result.
    """
    end = as_utc(window_end)
    start = end - config.span
    cache = cache or WindowCache()
    cache.bind(start, end, schema)

    # Complete transfer lists for every account fetched so far. An entry exists
    # only for keys requested explicitly, so it never holds a partial list.
    touching = cache.touching

    def ensure_loaded(keys: Iterable[str]) -> None:
        missing = sorted({k for k in keys if k not in touching})
        if not missing:
            return
        wanted = set(missing)
        for k in missing:
            touching[k] = []
        seen: Set[str] = set()
        for t in source.fetch_touching(missing, start, end):
            if t.key in seen or not in_window(t.occurred_at, start, end):
                continue
            seen.add(t.key)
            if t.source in wanted:
                touching[t.source].append(t)
            if t.target in wanted and t.target != t.source:
                touching[t.target].append(t)

    hops: Dict[str, int] = {seed: 0}
    frontier = [seed]
    truncated_nodes = False
    hubs: List[str] = []

    for depth in range(1, config.hops + 1):
        ensure_loaded(frontier)
        candidates: Dict[str, List[float]] = {}  # key -> [value, latest_ts]
        for key in frontier:
            transfers = touching[key]
            partners = {t.target if t.source == key else t.source for t in transfers}
            if key != seed and len(partners) > config.hub_partner_limit:
                hubs.append(key)
                continue
            for t in transfers:
                other = t.target if t.source == key else t.source
                if other == key or other in hops:
                    continue
                entry = candidates.setdefault(other, [0.0, 0.0])
                entry[0] += t.amount
                entry[1] = max(entry[1], t.occurred_at.timestamp())

        room = config.max_nodes - len(hops)
        # Keep the strongest money links first; ties broken by recency then key
        ranked = sorted(candidates, key=lambda k: (-candidates[k][0], -candidates[k][1], k))
        if len(ranked) > room:
            truncated_nodes = True
            ranked = ranked[: max(room, 0)]
        for key in ranked:
            hops[key] = depth
        frontier = ranked
        if not frontier:
            break

    # Every member needs its full institution-wide transfer list for its features
    ensure_loaded(hops)

    node_keys = [seed] + sorted((k for k in hops if k != seed), key=lambda k: (hops[k], k))
    for k in node_keys:
        if k not in cache.stats:
            cache.stats[k] = compute_account_stats(k, touching[k], start, end, schema)
    stats = {k: cache.stats[k] for k in node_keys}
    if schema.include_profile:
        missing = [k for k in node_keys if k not in cache.profiles]
        if missing:
            found = source.profiles(missing)
            for k in missing:
                cache.profiles[k] = found.get(k) or AccountProfile(key=k)
        profiles = {k: cache.profiles[k] for k in node_keys}
    else:
        profiles = {k: AccountProfile(key=k) for k in node_keys}

    # Induced edges: transfers with both endpoints inside the window
    members = set(node_keys)
    by_key: Dict[str, TransferRecord] = {}
    for key in node_keys:
        for t in touching[key]:
            if t.source in members and t.target in members and t.source != t.target:
                by_key[t.key] = t
    edges = sorted(by_key.values(), key=lambda t: (t.occurred_at, t.key))
    truncated_edges = False
    if len(edges) > config.max_edges:
        truncated_edges = True
        keep = sorted(edges, key=lambda t: (-t.amount, -t.occurred_at.timestamp(), t.key))
        kept = {t.key for t in keep[: config.max_edges]}
        edges = [t for t in edges if t.key in kept]

    index = {k: i for i, k in enumerate(node_keys)}
    node_rows = [node_feature_vector(profiles[k], stats[k], k == seed, schema) for k in node_keys]
    edge_rows = [edge_feature_vector(t, stats[t.source], stats[t.target], schema) for t in edges]
    edge_index = (
        np.asarray([[index[t.source] for t in edges], [index[t.target] for t in edges]], dtype=np.int64)
        if edges
        else np.zeros((2, 0), dtype=np.int64)
    )

    return NeighbourhoodWindow(
        seed=seed,
        window_start=start,
        window_end=end,
        config=config,
        node_keys=node_keys,
        node_hops={k: hops[k] for k in node_keys},
        node_features=as_matrix(node_rows, schema.node_dim),
        edge_keys=[t.key for t in edges],
        edge_index=edge_index,
        edge_features=as_matrix(edge_rows, schema.edge_dim),
        edge_minutes_before_end=np.asarray(
            [(end - t.occurred_at).total_seconds() / 60.0 for t in edges], dtype=np.float32
        ),
        stats=stats,
        profiles=profiles,
        transfers=edges,
        truncated_nodes=truncated_nodes,
        truncated_edges=truncated_edges,
        hubs_not_expanded=sorted(hubs),
        schema=schema,
    )


# ---------------------------------------------------------------------------
# In-memory source (synthetic training graphs, tests)
# ---------------------------------------------------------------------------


class InMemoryTransferSource:
    """A `TransferSource` over transfers already in memory."""

    def __init__(
        self,
        transfers: Iterable[TransferRecord],
        profiles: Optional[Iterable[AccountProfile]] = None,
    ):
        self._by_account: Dict[str, List[TransferRecord]] = {}
        for t in transfers:
            self._by_account.setdefault(t.source, []).append(t)
            if t.target != t.source:
                self._by_account.setdefault(t.target, []).append(t)
        self._profiles = {p.key: p for p in profiles or []}

    @property
    def account_keys(self) -> List[str]:
        return sorted(set(self._by_account) | set(self._profiles))

    def fetch_touching(
        self, keys: Sequence[str], start: datetime, end: datetime
    ) -> List[TransferRecord]:
        out: Dict[str, TransferRecord] = {}
        for key in keys:
            for t in self._by_account.get(key, []):
                if in_window(t.occurred_at, start, end):
                    out[t.key] = t
        return list(out.values())

    def profiles(self, keys: Sequence[str]) -> Dict[str, AccountProfile]:
        return {k: self._profiles[k] for k in keys if k in self._profiles}

    @classmethod
    def from_graph_records(cls, nodes, edges) -> "InMemoryTransferSource":
        """Adapt v1 `NodeRecord` / `EdgeRecord` lists (the synthetic generator).

        v1 records carry no channel, so every transfer maps to the OTHER rail.
        Used by tests; training data comes from AMLworld.
        """
        from app.graph.builder import is_high_risk_country

        profiles = [
            AccountProfile(
                key=n.key,
                entity_type=n.entity_type,
                is_internal=True,
                account_age_days=int(n.account_age_days),
                is_dormant=bool(n.is_dormant),
                high_risk_jurisdiction=is_high_risk_country(n.country),
                label=n.label,
            )
            for n in nodes
        ]
        transfers = [
            TransferRecord(
                key=e.key,
                source=e.source,
                target=e.target,
                amount=float(e.amount),
                occurred_at=as_utc(e.occurred_at),
                is_international=bool(e.is_international),
            )
            for e in edges
        ]
        return cls(transfers, profiles)
