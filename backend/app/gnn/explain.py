"""Turns GNN output + graph structure into investigator-readable signals.

Every signal is derived from a measured graph quantity and carries the number
behind it, so an analyst can verify the claim against the graph rather than
taking a score on trust.

Framing rule enforced here: signals are described as observed structural
characteristics and model indicators. Nothing in this module asserts criminality.
"""

from __future__ import annotations

from typing import Dict, List

from app.gnn.base import GNNOutput
from app.graph.patterns import PatternCandidate
from app.graph.types import GraphSnapshot

# The standing disclaimer attached to every network assessment.
NETWORK_DISCLAIMER = (
    "Model-generated risk indicators. These signals describe structural patterns "
    "observed in transaction data and do not establish that any offence occurred. "
    "A risk score is not proof of criminal activity and is not a substitute for "
    "human investigation and formal due diligence."
)

SIGNAL_VOCABULARY: List[Dict[str, str]] = [
    {"code": "HIGH_CONNECTIVITY", "label": "High connectivity", "meaning": "Participants are unusually densely interconnected for a cluster of this size."},
    {"code": "INTERMEDIARY_DEPTH", "label": "Multiple intermediary accounts", "meaning": "Value traverses several accounts that retain almost none of it."},
    {"code": "CIRCULAR_FLOW", "label": "Circular transaction flow", "meaning": "Value returns toward an account it previously left."},
    {"code": "RAPID_MOVEMENT", "label": "Rapid movement of funds", "meaning": "Funds are forwarded onward very soon after arriving."},
    {"code": "RELATIONSHIP_DENSITY", "label": "Unusual relationship density", "meaning": "Counterparty relationships cluster more tightly than typical activity."},
    {"code": "TIMING_SYNCHRONY", "label": "Similar transaction timing", "meaning": "Transfers occur in tight, near-synchronised bursts."},
    {"code": "AMOUNT_UNIFORMITY", "label": "Uniform transaction amounts", "meaning": "Amounts are near-identical, often just under a reporting threshold."},
    {"code": "YOUNG_ACCOUNTS", "label": "Recently opened accounts", "meaning": "Several participants were onboarded shortly before the activity."},
    {"code": "PASS_THROUGH", "label": "Pass-through behaviour", "meaning": "Accounts move on nearly everything they receive, retaining no balance."},
    {"code": "CROSS_BORDER", "label": "Cross-border exposure", "meaning": "Part of the flow crosses jurisdictions."},
    {"code": "VALUE_CONCENTRATION", "label": "Value concentration", "meaning": "A large share of total flow passes through one or two accounts."},
    {"code": "GNN_NODE_CONSENSUS", "label": "Model flags multiple participants", "meaning": "The graph model independently scores several participants as elevated."},
]


def _signal(code: str, label: str, contribution: float, detail: str) -> Dict[str, object]:
    return {
        "code": code,
        "label": label,
        "contribution": round(max(contribution, 0.0), 1),
        "detail": detail,
    }


def build_network_signals(
    snapshot: GraphSnapshot,
    output: GNNOutput,
    candidate: PatternCandidate | None = None,
) -> List[Dict[str, object]]:
    """Derive the contributing-signal list shown beside a network risk score."""
    signals: List[Dict[str, object]] = []
    n_nodes = max(snapshot.num_nodes, 1)
    n_edges = snapshot.num_edges

    # --- Connectivity / density -------------------------------------------
    density = n_edges / max(n_nodes * (n_nodes - 1), 1)
    if density > 0.12 or n_edges >= n_nodes * 1.4:
        signals.append(
            _signal(
                "HIGH_CONNECTIVITY",
                "High connectivity",
                min(density * 100, 22),
                f"{n_edges} transfers across {n_nodes} accounts "
                f"(edge density {density:.2f}); denser than typical retail activity.",
            )
        )

    # --- Pass-through / intermediaries ------------------------------------
    pass_through_nodes = [
        key
        for key, stats in snapshot.node_stats.items()
        if stats.get("pass_through_ratio", 0.0) >= 0.75
        and stats.get("degree_in", 0) >= 1
        and stats.get("degree_out", 0) >= 1
    ]
    if pass_through_nodes:
        signals.append(
            _signal(
                "PASS_THROUGH",
                "Pass-through behaviour",
                min(len(pass_through_nodes) * 5.0, 20),
                f"{len(pass_through_nodes)} account(s) forward nearly all value received, "
                "retaining no meaningful balance.",
            )
        )
    if len(pass_through_nodes) >= 2:
        signals.append(
            _signal(
                "INTERMEDIARY_DEPTH",
                "Multiple intermediary accounts",
                min(len(pass_through_nodes) * 4.0, 18),
                f"Value traverses {len(pass_through_nodes)} chained intermediary account(s).",
            )
        )

    # --- Relay speed -------------------------------------------------------
    relay_scores = [s.get("relay_speed", 0.0) for s in snapshot.node_stats.values()]
    avg_relay = sum(relay_scores) / max(len(relay_scores), 1)
    if avg_relay > 0.35:
        signals.append(
            _signal(
                "RAPID_MOVEMENT",
                "Rapid movement of funds",
                min(avg_relay * 26, 20),
                f"Mean onward-transfer immediacy {avg_relay:.2f} (1.0 = forwarded instantly); "
                "funds do not rest in these accounts.",
            )
        )

    # --- Timing synchrony --------------------------------------------------
    timing = [s.get("timing_concentration", 0.0) for s in snapshot.node_stats.values()]
    avg_timing = sum(timing) / max(len(timing), 1)
    if avg_timing > 0.45:
        signals.append(
            _signal(
                "TIMING_SYNCHRONY",
                "Similar transaction timing",
                min(avg_timing * 18, 14),
                f"{avg_timing * 100:.0f}% of each participant's activity falls inside a "
                "single hour, indicating coordinated bursts.",
            )
        )

    # --- Amount uniformity -------------------------------------------------
    amounts = [e.amount for e in snapshot.edges]
    if len(amounts) >= 4:
        mean_amount = sum(amounts) / len(amounts)
        spread = (max(amounts) - min(amounts)) / mean_amount if mean_amount else 1.0
        uniformity = max(0.0, 1.0 - min(spread, 1.0))
        if uniformity > 0.5:
            signals.append(
                _signal(
                    "AMOUNT_UNIFORMITY",
                    "Uniform transaction amounts",
                    min(uniformity * 18, 15),
                    f"Transfer amounts are {uniformity * 100:.0f}% uniform around "
                    f"INR {mean_amount:,.0f}.",
                )
            )

    # --- Circular flow -----------------------------------------------------
    if candidate and candidate.pattern == "CIRCULAR":
        signals.append(
            _signal(
                "CIRCULAR_FLOW",
                "Circular transaction flow",
                20,
                candidate.description,
            )
        )

    # --- Young accounts ----------------------------------------------------
    young = [
        key
        for key, record in snapshot.nodes.items()
        if record.account_age_days <= 180
    ]
    if young:
        signals.append(
            _signal(
                "YOUNG_ACCOUNTS",
                "Recently opened accounts",
                min(len(young) * 3.0, 14),
                f"{len(young)} participant account(s) opened within the last 180 days.",
            )
        )

    # --- Cross-border ------------------------------------------------------
    intl = [e for e in snapshot.edges if e.is_international]
    if intl:
        share = len(intl) / max(n_edges, 1)
        signals.append(
            _signal(
                "CROSS_BORDER",
                "Cross-border exposure",
                min(share * 20, 12),
                f"{len(intl)} of {n_edges} transfers cross jurisdictions ({share * 100:.0f}%).",
            )
        )

    # --- Value concentration ----------------------------------------------
    total_flow = snapshot.total_flow()
    if total_flow > 0 and snapshot.node_stats:
        top_node, top_stats = max(
            snapshot.node_stats.items(),
            key=lambda kv: kv[1].get("total_in", 0.0) + kv[1].get("total_out", 0.0),
        )
        top_volume = top_stats.get("total_in", 0.0) + top_stats.get("total_out", 0.0)
        share = top_volume / (total_flow * 2)
        if share > 0.35:
            signals.append(
                _signal(
                    "VALUE_CONCENTRATION",
                    "Value concentration",
                    min(share * 20, 14),
                    f"{share * 100:.0f}% of cluster throughput passes through a single "
                    f"account ({top_node}).",
                )
            )

    # --- Model consensus ---------------------------------------------------
    flagged = [k for k, v in output.node_scores.items() if v >= 60]
    if flagged:
        engine_kind = "graph neural network" if output.trained else "analytic graph engine"
        signals.append(
            _signal(
                "GNN_NODE_CONSENSUS",
                "Model flags multiple participants",
                min(len(flagged) * 4.0, 20),
                f"The {engine_kind} independently scores {len(flagged)} of {n_nodes} "
                "participants at 60/100 or above.",
            )
        )

    signals.sort(key=lambda s: s["contribution"], reverse=True)
    return signals


def structural_metrics(
    snapshot: GraphSnapshot, candidate: PatternCandidate | None = None
) -> Dict[str, object]:
    """The measured graph quantities backing the signals above."""
    n_nodes = max(snapshot.num_nodes, 1)
    n_edges = snapshot.num_edges
    relay = [s.get("relay_speed", 0.0) for s in snapshot.node_stats.values()]
    pass_through = [s.get("pass_through_ratio", 0.0) for s in snapshot.node_stats.values()]

    metrics: Dict[str, object] = {
        "nodes": snapshot.num_nodes,
        "edges": n_edges,
        "edge_density": round(n_edges / max(n_nodes * (n_nodes - 1), 1), 4),
        "total_flow": round(snapshot.total_flow(), 2),
        "avg_pass_through_ratio": round(sum(pass_through) / max(len(pass_through), 1), 3),
        "avg_relay_immediacy": round(sum(relay) / max(len(relay), 1), 3),
        "intermediary_count": sum(1 for p in pass_through if p >= 0.75),
        "cross_border_edges": sum(1 for e in snapshot.edges if e.is_international),
    }
    if snapshot.edges:
        times = [e.occurred_at for e in snapshot.edges]
        span = max(times) - min(times)
        metrics["span_hours"] = round(span.total_seconds() / 3600.0, 2)
        metrics["first_seen"] = min(times).isoformat()
        metrics["last_seen"] = max(times).isoformat()
    if candidate:
        metrics.update({f"pattern_{k}": v for k, v in candidate.metrics.items()})
        metrics["structural_confidence"] = round(candidate.structural_score, 3)
    return metrics
