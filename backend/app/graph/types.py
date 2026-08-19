"""Graph representation shared by the graph engine, the GNN and its trainer.

The single most important property of this module: `build_snapshot()` is the
ONLY place node/edge features are computed. The synthetic training generator and
the live database builder both hand it plain `NodeRecord` / `EdgeRecord` lists,
so the feature space at training time and at inference time cannot drift apart.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Feature contracts
# ---------------------------------------------------------------------------

NODE_FEATURE_SPEC: List[Tuple[str, str]] = [
    ("in_volume_log", "Inbound value (log-scaled)"),
    ("out_volume_log", "Outbound value (log-scaled)"),
    ("degree_in", "Number of paying-in counterparties"),
    ("degree_out", "Number of paid-out counterparties"),
    ("pass_through_ratio", "Balance of inflow against outflow"),
    ("net_flow_ratio", "Net accumulation vs pass-through"),
    ("avg_amount_log", "Average transaction size (log-scaled)"),
    ("amount_dispersion", "Variability of transaction sizes"),
    ("account_age_norm", "Account age"),
    ("timing_concentration", "Share of activity in the busiest hour"),
    ("unique_in_partners", "Distinct inbound partners"),
    ("unique_out_partners", "Distinct outbound partners"),
    ("round_amount_ratio", "Share of round-value transactions"),
    ("dormant_flag", "Dormant-account flag"),
    ("international_ratio", "Share of cross-border activity"),
    ("relay_speed", "Speed of onward transfer after receipt"),
]

EDGE_FEATURE_SPEC: List[Tuple[str, str]] = [
    ("amount_log", "Transfer amount (log-scaled)"),
    ("share_of_sender_out", "Share of the sender's total outflow"),
    ("share_of_receiver_in", "Share of the receiver's total inflow"),
    ("relay_latency", "How quickly the sender forwarded received funds"),
    ("international", "Cross-border flag"),
    ("round_amount", "Round-value flag"),
]

NODE_FEATURE_NAMES = [name for name, _ in NODE_FEATURE_SPEC]
EDGE_FEATURE_NAMES = [name for name, _ in EDGE_FEATURE_SPEC]
NODE_FEATURE_DIM = len(NODE_FEATURE_SPEC)
EDGE_FEATURE_DIM = len(EDGE_FEATURE_SPEC)

# Value scale used to log-normalise money amounts into roughly [0, 1]
_MONEY_LOG_SCALE = 20.0
_DEGREE_SCALE = 20.0


# ---------------------------------------------------------------------------
# Input records
# ---------------------------------------------------------------------------


@dataclass
class NodeRecord:
    """A graph node: an account, wallet, merchant or company."""

    key: str
    label: str = ""
    entity_type: str = "ACCOUNT"
    account_age_days: int = 365
    is_dormant: bool = False
    balance: float = 0.0
    country: str = "India"
    city: str = "Mumbai"
    institution: str = "Meridian Bank"
    customer_ref: Optional[str] = None
    db_id: Optional[int] = None


@dataclass
class EdgeRecord:
    """A graph edge: one transaction moving value from `source` to `target`."""

    key: str
    source: str
    target: str
    amount: float
    occurred_at: datetime
    txn_type: str = "TRANSFER"
    is_international: bool = False
    db_id: Optional[int] = None
    risk_score: float = 0.0


@dataclass
class GraphSnapshot:
    """Featurised graph ready for GNN inference."""

    node_keys: List[str]
    node_features: np.ndarray  # (N, NODE_FEATURE_DIM)
    edge_index: np.ndarray  # (2, E) int64 - row 0 = source idx, row 1 = target idx
    edge_features: np.ndarray  # (E, EDGE_FEATURE_DIM)
    edge_keys: List[str] = field(default_factory=list)
    nodes: Dict[str, NodeRecord] = field(default_factory=dict)
    edges: List[EdgeRecord] = field(default_factory=list)
    node_stats: Dict[str, Dict[str, float]] = field(default_factory=dict)

    @property
    def num_nodes(self) -> int:
        return len(self.node_keys)

    @property
    def num_edges(self) -> int:
        return int(self.edge_index.shape[1]) if self.edge_index.size else 0

    def index_of(self, key: str) -> int:
        return self._index_map[key]

    def __post_init__(self) -> None:
        self._index_map = {key: i for i, key in enumerate(self.node_keys)}

    def total_flow(self) -> float:
        return float(sum(e.amount for e in self.edges))

    def subgraph(self, keys: Sequence[str]) -> "GraphSnapshot":
        """Extract an induced subgraph, re-featurising from the retained edges."""
        keep = set(keys)
        nodes = [self.nodes[k] for k in keys if k in self.nodes]
        edges = [e for e in self.edges if e.source in keep and e.target in keep]
        return build_snapshot(nodes, edges)


# ---------------------------------------------------------------------------
# Featurisation - the shared train/inference path
# ---------------------------------------------------------------------------


def _is_round(amount: float) -> bool:
    """Round-value heuristic: exact multiples of 1k / 10k / 100k."""
    for unit in (100_000, 10_000, 1_000):
        if amount >= unit and abs(amount % unit) < 1e-6:
            return True
    return False


def _safe_log_scale(value: float) -> float:
    return float(min(math.log1p(max(value, 0.0)) / _MONEY_LOG_SCALE, 1.5))


def build_snapshot(
    nodes: Sequence[NodeRecord], edges: Sequence[EdgeRecord]
) -> GraphSnapshot:
    """Compute node and edge feature matrices from raw records."""
    node_list = list(nodes)
    node_keys = [n.key for n in node_list]
    index_map = {key: i for i, key in enumerate(node_keys)}
    node_map = {n.key: n for n in node_list}

    # Keep only edges whose endpoints are present, and ignore self-loops
    valid_edges = [
        e
        for e in edges
        if e.source in index_map and e.target in index_map and e.source != e.target
    ]

    n = len(node_keys)
    # --- Per-node aggregates ------------------------------------------------
    in_amounts: Dict[str, List[float]] = {k: [] for k in node_keys}
    out_amounts: Dict[str, List[float]] = {k: [] for k in node_keys}
    in_partners: Dict[str, set] = {k: set() for k in node_keys}
    out_partners: Dict[str, set] = {k: set() for k in node_keys}
    times: Dict[str, List[datetime]] = {k: [] for k in node_keys}
    round_hits: Dict[str, int] = {k: 0 for k in node_keys}
    intl_hits: Dict[str, int] = {k: 0 for k in node_keys}
    # Earliest inbound timestamp, used for relay-speed
    first_in: Dict[str, Optional[datetime]] = {k: None for k in node_keys}

    for edge in valid_edges:
        out_amounts[edge.source].append(edge.amount)
        in_amounts[edge.target].append(edge.amount)
        out_partners[edge.source].add(edge.target)
        in_partners[edge.target].add(edge.source)
        times[edge.source].append(edge.occurred_at)
        times[edge.target].append(edge.occurred_at)
        if _is_round(edge.amount):
            round_hits[edge.source] += 1
            round_hits[edge.target] += 1
        if edge.is_international:
            intl_hits[edge.source] += 1
            intl_hits[edge.target] += 1
        prev = first_in[edge.target]
        if prev is None or edge.occurred_at < prev:
            first_in[edge.target] = edge.occurred_at

    node_features = np.zeros((n, NODE_FEATURE_DIM), dtype=np.float32)
    node_stats: Dict[str, Dict[str, float]] = {}

    for key in node_keys:
        idx = index_map[key]
        record = node_map[key]
        ins, outs = in_amounts[key], out_amounts[key]
        total_in, total_out = float(sum(ins)), float(sum(outs))
        all_amounts = ins + outs
        count = len(all_amounts)
        avg_amount = float(np.mean(all_amounts)) if all_amounts else 0.0
        std_amount = float(np.std(all_amounts)) if len(all_amounts) > 1 else 0.0
        dispersion = min(std_amount / avg_amount, 3.0) / 3.0 if avg_amount > 0 else 0.0

        denom = max(total_in, total_out)
        pass_through = (min(total_in, total_out) / denom) if denom > 0 else 0.0
        flow_total = total_in + total_out
        net_flow = ((total_in - total_out) / flow_total) if flow_total > 0 else 0.0

        # Timing concentration: busiest single hour as a share of all activity
        timing_concentration = 0.0
        if count > 1:
            hour_buckets: Dict[int, int] = {}
            base = min(times[key])
            for ts in times[key]:
                bucket = int((ts - base).total_seconds() // 3600)
                hour_buckets[bucket] = hour_buckets.get(bucket, 0) + 1
            timing_concentration = max(hour_buckets.values()) / count

        # Relay speed: how fast value left after the first inbound arrived
        relay_speed = 0.0
        if first_in[key] is not None and outs:
            outgoing_after = [
                e.occurred_at
                for e in valid_edges
                if e.source == key and e.occurred_at >= first_in[key]
            ]
            if outgoing_after:
                minutes = (min(outgoing_after) - first_in[key]).total_seconds() / 60.0
                # 1.0 = forwarded instantly, decaying with a 90-minute half-life
                relay_speed = float(math.exp(-max(minutes, 0.0) / 90.0))

        vec = node_features[idx]
        vec[0] = _safe_log_scale(total_in)
        vec[1] = _safe_log_scale(total_out)
        vec[2] = min(len(ins) / _DEGREE_SCALE, 2.0)
        vec[3] = min(len(outs) / _DEGREE_SCALE, 2.0)
        vec[4] = pass_through
        vec[5] = net_flow
        vec[6] = _safe_log_scale(avg_amount)
        vec[7] = dispersion
        vec[8] = min(record.account_age_days / 3650.0, 1.0)
        vec[9] = timing_concentration
        vec[10] = min(len(in_partners[key]) / _DEGREE_SCALE, 2.0)
        vec[11] = min(len(out_partners[key]) / _DEGREE_SCALE, 2.0)
        vec[12] = (round_hits[key] / count) if count else 0.0
        vec[13] = 1.0 if record.is_dormant else 0.0
        vec[14] = (intl_hits[key] / count) if count else 0.0
        vec[15] = relay_speed

        node_stats[key] = {
            "total_in": total_in,
            "total_out": total_out,
            "degree_in": float(len(ins)),
            "degree_out": float(len(outs)),
            "unique_in": float(len(in_partners[key])),
            "unique_out": float(len(out_partners[key])),
            "pass_through_ratio": pass_through,
            "avg_amount": avg_amount,
            "txn_count": float(count),
            "relay_speed": relay_speed,
            "timing_concentration": timing_concentration,
            "round_ratio": (round_hits[key] / count) if count else 0.0,
        }

    # --- Edge features ------------------------------------------------------
    e_count = len(valid_edges)
    edge_index = np.zeros((2, e_count), dtype=np.int64)
    edge_features = np.zeros((e_count, EDGE_FEATURE_DIM), dtype=np.float32)
    edge_keys: List[str] = []

    for i, edge in enumerate(valid_edges):
        src_idx, dst_idx = index_map[edge.source], index_map[edge.target]
        edge_index[0, i] = src_idx
        edge_index[1, i] = dst_idx
        edge_keys.append(edge.key)

        sender_out = node_stats[edge.source]["total_out"] or 1.0
        receiver_in = node_stats[edge.target]["total_in"] or 1.0

        # Relay latency: gap between the sender receiving funds and sending them on
        relay_latency = 0.0
        sender_first_in = first_in[edge.source]
        if sender_first_in is not None and edge.occurred_at >= sender_first_in:
            minutes = (edge.occurred_at - sender_first_in).total_seconds() / 60.0
            relay_latency = float(math.exp(-max(minutes, 0.0) / 90.0))

        row = edge_features[i]
        row[0] = _safe_log_scale(edge.amount)
        row[1] = min(edge.amount / sender_out, 1.0)
        row[2] = min(edge.amount / receiver_in, 1.0)
        row[3] = relay_latency
        row[4] = 1.0 if edge.is_international else 0.0
        row[5] = 1.0 if _is_round(edge.amount) else 0.0

    return GraphSnapshot(
        node_keys=node_keys,
        node_features=node_features,
        edge_index=edge_index,
        edge_features=edge_features,
        edge_keys=edge_keys,
        nodes=node_map,
        edges=valid_edges,
        node_stats=node_stats,
    )
