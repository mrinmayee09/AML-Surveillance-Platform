"""Structural laundering-typology detection over the transaction graph.

These are real graph algorithms operating on the directed money-flow graph:
Tarjan strongly-connected components for circular flow, bounded-depth DFS for
layering chains, and degree/temporal analysis for fan-out, fan-in and smurfing.

The GNN consumes and refines these candidates; it does not replace them. Keeping
structure detection explicit means an investigator can always be told *which
topology* triggered a cluster, in graph terms they can verify by eye.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Dict, List, Optional, Sequence, Set, Tuple

from app.graph.types import EdgeRecord, GraphSnapshot

# ---------------------------------------------------------------------------
# Tunables. Exposed here (rather than inline) so the Rules Engine page can
# describe the thresholds the structural layer actually uses.
# ---------------------------------------------------------------------------
MIN_CYCLE_LEN = 3
MAX_CYCLE_LEN = 8
MIN_CHAIN_LEN = 3
MAX_CHAIN_LEN = 7
PASS_THROUGH_MIN = 0.75
RELAY_WINDOW = timedelta(hours=6)
# A layering hop forwards almost everything it received. Amounts along the chain
# must therefore stay within this band of the previous hop, otherwise the "chain"
# is just two unrelated transfers that happen to share an account.
CHAIN_AMOUNT_BAND = (0.60, 1.08)
FAN_MIN_DEGREE = 5
FAN_WINDOW = timedelta(hours=24)
# A fan is only structurally interesting when the amounts are near-uniform or the
# burst is fast. Legitimate collections/payroll are wide-spread and slow, so this
# gate is what stops the detector from degenerating into a degree counter.
FAN_MIN_UNIFORMITY = 0.55
FAN_FAST_BURST = timedelta(hours=6)
SMURF_MAX_AMOUNT = 200_000.0
SMURF_MIN_COUNT = 6


@dataclass
class PatternCandidate:
    """A structural finding: which nodes/edges, which topology, and why."""

    pattern: str
    node_keys: List[str]
    edge_keys: List[str]
    # 0-1 structural confidence, before the GNN weighs in
    structural_score: float
    metrics: Dict[str, float] = field(default_factory=dict)
    description: str = ""
    roles: Dict[str, str] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.node_keys)


# ---------------------------------------------------------------------------
# Adjacency helpers
# ---------------------------------------------------------------------------


def _adjacency(
    edges: Sequence[EdgeRecord],
) -> Tuple[Dict[str, List[EdgeRecord]], Dict[str, List[EdgeRecord]]]:
    out_adj: Dict[str, List[EdgeRecord]] = defaultdict(list)
    in_adj: Dict[str, List[EdgeRecord]] = defaultdict(list)
    for edge in edges:
        out_adj[edge.source].append(edge)
        in_adj[edge.target].append(edge)
    return out_adj, in_adj


def _edge_lookup(edges: Sequence[EdgeRecord]) -> Dict[Tuple[str, str], List[EdgeRecord]]:
    lookup: Dict[Tuple[str, str], List[EdgeRecord]] = defaultdict(list)
    for edge in edges:
        lookup[(edge.source, edge.target)].append(edge)
    return lookup


# ---------------------------------------------------------------------------
# 1. Circular flow - strongly connected components
# ---------------------------------------------------------------------------


def strongly_connected_components(
    node_keys: Sequence[str], edges: Sequence[EdgeRecord]
) -> List[List[str]]:
    """Tarjan's SCC algorithm, iterative so deep graphs cannot blow the stack."""
    out_adj, _ = _adjacency(edges)
    index_counter = [0]
    stack: List[str] = []
    on_stack: Set[str] = set()
    indices: Dict[str, int] = {}
    lowlink: Dict[str, int] = {}
    components: List[List[str]] = []

    for root in node_keys:
        if root in indices:
            continue
        # (node, iterator over successors)
        work: List[Tuple[str, int]] = [(root, 0)]
        successors: Dict[str, List[str]] = {}
        indices[root] = lowlink[root] = index_counter[0]
        index_counter[0] += 1
        stack.append(root)
        on_stack.add(root)
        successors[root] = [e.target for e in out_adj.get(root, [])]

        while work:
            node, pointer = work[-1]
            if pointer < len(successors[node]):
                work[-1] = (node, pointer + 1)
                child = successors[node][pointer]
                if child not in indices:
                    indices[child] = lowlink[child] = index_counter[0]
                    index_counter[0] += 1
                    stack.append(child)
                    on_stack.add(child)
                    successors[child] = [e.target for e in out_adj.get(child, [])]
                    work.append((child, 0))
                elif child in on_stack:
                    lowlink[node] = min(lowlink[node], indices[child])
            else:
                work.pop()
                if work:
                    parent = work[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[node])
                if lowlink[node] == indices[node]:
                    component: List[str] = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        component.append(member)
                        if member == node:
                            break
                    if len(component) > 1:
                        components.append(component)

    return components


def detect_circular_flow(snapshot: GraphSnapshot) -> List[PatternCandidate]:
    """Value that returns to (or near) its origin after passing through others."""
    found: List[PatternCandidate] = []
    components = strongly_connected_components(snapshot.node_keys, snapshot.edges)

    for component in components:
        if not (MIN_CYCLE_LEN <= len(component) <= MAX_CYCLE_LEN * 2):
            continue
        members = set(component)
        internal = [
            e for e in snapshot.edges if e.source in members and e.target in members
        ]
        if len(internal) < len(component):
            continue

        flow = sum(e.amount for e in internal)
        span = max(e.occurred_at for e in internal) - min(
            e.occurred_at for e in internal
        )
        span_hours = max(span.total_seconds() / 3600.0, 0.01)

        # Value conservation around the loop: laundering cycles return most of
        # the principal, minus a skim.
        amounts = [e.amount for e in internal]
        conservation = min(amounts) / max(amounts) if max(amounts) > 0 else 0.0
        pass_through = sum(
            snapshot.node_stats.get(k, {}).get("pass_through_ratio", 0.0)
            for k in component
        ) / len(component)

        score = min(
            0.45
            + 0.25 * conservation
            + 0.2 * pass_through
            + 0.1 * min(72.0 / span_hours, 1.0),
            0.99,
        )
        found.append(
            PatternCandidate(
                pattern="CIRCULAR",
                node_keys=sorted(members),
                edge_keys=[e.key for e in internal],
                structural_score=score,
                metrics={
                    "cycle_length": float(len(component)),
                    "internal_edges": float(len(internal)),
                    "total_flow": flow,
                    "value_conservation": round(conservation, 3),
                    "span_hours": round(span_hours, 2),
                    "avg_pass_through": round(pass_through, 3),
                },
                description=(
                    f"Value circulates through {len(component)} accounts and returns "
                    f"toward its origin across {len(internal)} transfers "
                    f"({conservation * 100:.0f}% of principal preserved around the loop)."
                ),
                roles={k: "CYCLE_MEMBER" for k in component},
            )
        )
    return found


# ---------------------------------------------------------------------------
# 2. Layering chains - bounded-depth DFS over rapid pass-through hops
# ---------------------------------------------------------------------------


def detect_layering_chains(snapshot: GraphSnapshot) -> List[PatternCandidate]:
    """Funds relayed through a chain of intermediaries that retain almost nothing."""
    out_adj, in_adj = _adjacency(snapshot.edges)
    found: List[PatternCandidate] = []
    seen_signatures: Set[Tuple[str, ...]] = set()

    def is_relay(key: str) -> bool:
        stats = snapshot.node_stats.get(key, {})
        return (
            stats.get("pass_through_ratio", 0.0) >= PASS_THROUGH_MIN
            and stats.get("degree_in", 0) >= 1
            and stats.get("degree_out", 0) >= 1
        )

    # Sources: nodes that push value out but are not themselves pure relays
    sources = [
        k
        for k in snapshot.node_keys
        if snapshot.node_stats.get(k, {}).get("degree_out", 0) >= 1 and not is_relay(k)
    ]

    for source in sources:
        # DFS along temporally-consistent, rapid hops
        stack: List[Tuple[str, List[str], List[EdgeRecord]]] = [(source, [source], [])]
        while stack:
            node, path, path_edges = stack.pop()
            if len(path) > MAX_CHAIN_LEN:
                continue
            for edge in out_adj.get(node, []):
                nxt = edge.target
                if nxt in path:
                    continue
                if path_edges and edge.occurred_at < path_edges[-1].occurred_at:
                    continue
                if path_edges:
                    gap = edge.occurred_at - path_edges[-1].occurred_at
                    if gap > RELAY_WINDOW:
                        continue
                    # Value continuity: a relay forwards what it received
                    prev_amount = path_edges[-1].amount
                    if prev_amount > 0:
                        ratio = edge.amount / prev_amount
                        if not (CHAIN_AMOUNT_BAND[0] <= ratio <= CHAIN_AMOUNT_BAND[1]):
                            continue
                new_path = path + [nxt]
                new_edges = path_edges + [edge]

                # A chain qualifies when every middle hop is a relay
                middles = new_path[1:-1]
                if len(new_path) >= MIN_CHAIN_LEN and middles and all(
                    is_relay(m) for m in middles
                ):
                    signature = tuple(new_path)
                    if signature not in seen_signatures:
                        seen_signatures.add(signature)
                        amounts = [e.amount for e in new_edges]
                        first_amount, last_amount = amounts[0], amounts[-1]
                        # Fraction of the original principal that survived the chain
                        preserved = (
                            min(last_amount / first_amount, 1.0) if first_amount > 0 else 0.0
                        )
                        span = new_edges[-1].occurred_at - new_edges[0].occurred_at
                        span_hours = max(span.total_seconds() / 3600.0, 0.01)
                        depth = len(middles)
                        # High preservation + many hops + short span = layering.
                        # Depth alone is capped so long benign trade chains do not
                        # dominate the score.
                        score = min(
                            0.34
                            + 0.09 * min(depth, 4)
                            + 0.24 * preserved
                            + 0.16 * min(6.0 / span_hours, 1.0),
                            0.99,
                        )
                        roles = {new_path[0]: "SOURCE", new_path[-1]: "CONVERGENCE"}
                        roles.update({m: "INTERMEDIARY" for m in middles})
                        found.append(
                            PatternCandidate(
                                pattern="LAYERED",
                                node_keys=list(new_path),
                                edge_keys=[e.key for e in new_edges],
                                structural_score=score,
                                metrics={
                                    "chain_length": float(len(new_path)),
                                    "intermediaries": float(depth),
                                    "total_flow": float(sum(amounts)),
                                    "value_preserved_pct": round(preserved * 100, 2),
                                    "span_hours": round(span_hours, 2),
                                },
                                description=(
                                    f"Funds moved through {depth} intermediary "
                                    f"account(s) in {span_hours:.1f}h. "
                                    f"{preserved * 100:.0f}% of the original value "
                                    "reached the final account, so each hop retained "
                                    "only a thin margin - consistent with layering "
                                    "rather than genuine trade."
                                ),
                                roles=roles,
                            )
                        )
                if len(new_path) <= MAX_CHAIN_LEN:
                    stack.append((nxt, new_path, new_edges))

    # Prefer the longest chain per source/destination pair
    found.sort(key=lambda c: (c.structural_score, c.size), reverse=True)
    deduped: List[PatternCandidate] = []
    covered: Set[Tuple[str, str]] = set()
    for cand in found:
        endpoints = (cand.node_keys[0], cand.node_keys[-1])
        if endpoints in covered:
            continue
        covered.add(endpoints)
        deduped.append(cand)
    return deduped


# ---------------------------------------------------------------------------
# 3. Fan-out / fan-in / smurfing
# ---------------------------------------------------------------------------


def detect_fan_structures(snapshot: GraphSnapshot) -> List[PatternCandidate]:
    out_adj, in_adj = _adjacency(snapshot.edges)
    found: List[PatternCandidate] = []

    for key in snapshot.node_keys:
        for direction, adj in (("FAN_OUT", out_adj), ("FAN_IN", in_adj)):
            edges = adj.get(key, [])
            if len(edges) < FAN_MIN_DEGREE:
                continue
            partners = {(e.target if direction == "FAN_OUT" else e.source) for e in edges}
            if len(partners) < FAN_MIN_DEGREE:
                continue

            edges_sorted = sorted(edges, key=lambda e: e.occurred_at)
            # Densest burst within the fan window
            best_window: List[EdgeRecord] = []
            for i, anchor in enumerate(edges_sorted):
                window = [
                    e
                    for e in edges_sorted[i:]
                    if e.occurred_at - anchor.occurred_at <= FAN_WINDOW
                ]
                if len(window) > len(best_window):
                    best_window = window
            if len(best_window) < FAN_MIN_DEGREE:
                continue

            amounts = [e.amount for e in best_window]
            avg = sum(amounts) / len(amounts)
            spread = (max(amounts) - min(amounts)) / avg if avg > 0 else 1.0
            uniformity = max(0.0, 1.0 - min(spread, 1.0))
            span = best_window[-1].occurred_at - best_window[0].occurred_at
            span_hours = max(span.total_seconds() / 3600.0, 0.01)
            window_partners = {
                (e.target if direction == "FAN_OUT" else e.source) for e in best_window
            }

            is_fast = span <= FAN_FAST_BURST
            # Gate: a wide, slow, non-uniform fan is ordinary commercial activity
            # (merchant collections, payroll). Require uniform amounts or a fast
            # burst before treating the structure as a candidate at all.
            if uniformity < FAN_MIN_UNIFORMITY and not is_fast:
                continue

            is_smurfing = (
                direction == "FAN_IN"
                and avg <= SMURF_MAX_AMOUNT
                and len(best_window) >= SMURF_MIN_COUNT
                and uniformity >= FAN_MIN_UNIFORMITY
            )
            pattern = "SMURFING" if is_smurfing else direction
            # Uniformity and burst speed carry the weight; degree only modulates.
            score = min(
                0.30
                + 0.02 * min(len(window_partners), 12)
                + 0.34 * uniformity
                + 0.20 * min(6.0 / span_hours, 1.0),
                0.97,
            )

            roles = {key: "DISTRIBUTOR" if direction == "FAN_OUT" else "CONVERGENCE"}
            roles.update({p: "PARTICIPANT" for p in window_partners})
            verb = "distributed to" if direction == "FAN_OUT" else "received from"
            interpretation = (
                "structuring/smurfing into a single collection account."
                if is_smurfing
                else (
                    "rapid dispersion of funds."
                    if direction == "FAN_OUT"
                    else "convergence of funds from many sources."
                )
            )
            found.append(
                PatternCandidate(
                    pattern=pattern,
                    node_keys=[key] + sorted(window_partners),
                    edge_keys=[e.key for e in best_window],
                    structural_score=score,
                    metrics={
                        "fan_degree": float(len(window_partners)),
                        "burst_transactions": float(len(best_window)),
                        "avg_amount": round(avg, 2),
                        "amount_uniformity": round(uniformity, 3),
                        "span_hours": round(span_hours, 2),
                        "total_flow": float(sum(amounts)),
                    },
                    description=(
                        f"One account {verb} {len(window_partners)} counterparties in "
                        f"{span_hours:.1f}h with {uniformity * 100:.0f}% amount "
                        f"uniformity, consistent with {interpretation}"
                    ),
                    roles=roles,
                )
            )
    return found


# ---------------------------------------------------------------------------
# 4. Clustering: merge overlapping candidates into investigable networks
# ---------------------------------------------------------------------------


def detect_all_patterns(snapshot: GraphSnapshot) -> List[PatternCandidate]:
    candidates: List[PatternCandidate] = []
    candidates.extend(detect_circular_flow(snapshot))
    candidates.extend(detect_layering_chains(snapshot))
    candidates.extend(detect_fan_structures(snapshot))
    return candidates


# Priority when two overlapping candidates disagree on the topology label
_PATTERN_PRIORITY = {
    "CIRCULAR": 5,
    "LAYERED": 4,
    "SMURFING": 3,
    "FAN_OUT": 2,
    "FAN_IN": 2,
    "PASS_THROUGH": 1,
    "NORMAL": 0,
}


def merge_candidates(
    candidates: Sequence[PatternCandidate], overlap_threshold: float = 0.5
) -> List[PatternCandidate]:
    """Union overlapping candidates so one cluster becomes one investigable case."""
    remaining = sorted(
        candidates,
        key=lambda c: (_PATTERN_PRIORITY.get(c.pattern, 0), c.structural_score, c.size),
        reverse=True,
    )
    merged: List[PatternCandidate] = []

    for cand in remaining:
        cand_nodes = set(cand.node_keys)
        target: Optional[PatternCandidate] = None
        for existing in merged:
            existing_nodes = set(existing.node_keys)
            overlap = len(cand_nodes & existing_nodes)
            smaller = min(len(cand_nodes), len(existing_nodes)) or 1
            if overlap / smaller >= overlap_threshold:
                target = existing
                break

        if target is None:
            merged.append(
                PatternCandidate(
                    pattern=cand.pattern,
                    node_keys=list(cand.node_keys),
                    edge_keys=list(cand.edge_keys),
                    structural_score=cand.structural_score,
                    metrics=dict(cand.metrics),
                    description=cand.description,
                    roles=dict(cand.roles),
                )
            )
            continue

        # Absorb into the existing cluster, keeping the stronger topology label
        target.node_keys = sorted(set(target.node_keys) | cand_nodes)
        target.edge_keys = sorted(set(target.edge_keys) | set(cand.edge_keys))
        target.structural_score = max(target.structural_score, cand.structural_score)
        if _PATTERN_PRIORITY.get(cand.pattern, 0) > _PATTERN_PRIORITY.get(
            target.pattern, 0
        ):
            target.pattern = cand.pattern
            target.description = cand.description
        for key, role in cand.roles.items():
            target.roles.setdefault(key, role)
        for key, value in cand.metrics.items():
            target.metrics.setdefault(key, value)

    return merged
