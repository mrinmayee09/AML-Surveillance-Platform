"""Reactive network layer: graph construction -> GNN -> suspicious subgraphs.

Pipeline implemented here:

    Graph Construction  (app.graph.builder)
            |
    Structural typology detection  (app.graph.patterns)
            |
    GNN inference on each candidate cluster  (app.gnn.*)
            |
    Suspicious nodes / edges / subgraphs  (persisted as Network rows)
            |
    Network risk score + contributing signals
            |
    Investigator visualisation  (served as GraphNode / GraphEdge)

The structural layer proposes candidates; the GNN scores them. Both contribute to
the final network risk, and the API reports which engine produced the score and
whether that engine is actually trained.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.types import utcnow
from app.gnn.base import GNNOutput
from app.gnn.explain import NETWORK_DISCLAIMER, build_network_signals, structural_metrics
from app.gnn.registry import get_gnn_engine
from app.graph import builder as graph_builder
from app.graph.patterns import PatternCandidate, detect_all_patterns, merge_candidates
from app.graph.types import GraphSnapshot
from app.models import (
    Account,
    Alert,
    Investigation,
    Network,
    NetworkEdge,
    NetworkNode,
    RiskAssessment,
    Transaction,
)
from app.models.enums import AlertSource, NetworkPattern
from app.schemas.common import ModelProvenance
from app.schemas.network import GNNSignal, GraphEdge, GraphNode, NetworkAssessment

# Blend between the learned score and the structural confidence.
GNN_WEIGHT = 0.6
STRUCTURAL_WEIGHT = 0.4
# A cluster is surfaced as suspicious at or above this composite score
SUSPICIOUS_THRESHOLD = 55.0
# Per-node / per-edge flag thresholds
NODE_FLAG_THRESHOLD = 60.0
EDGE_FLAG_THRESHOLD = 60.0
# Minimum cluster size worth an investigator's time
MIN_CLUSTER_NODES = 3


def _radial_layout(
    snapshot: GraphSnapshot, candidate: Optional[PatternCandidate]
) -> Dict[str, Tuple[float, float]]:
    """Deterministic layout hint so the graph view opens in a readable shape.

    Layered patterns are laid out left-to-right by hop; everything else gets a
    ring with the highest-throughput node at the centre. The frontend may still
    re-run its own force layout, but this guarantees a stable, sensible default.
    """
    import math

    positions: Dict[str, Tuple[float, float]] = {}
    keys = snapshot.node_keys
    if not keys:
        return positions

    roles = candidate.roles if candidate else {}
    pattern = candidate.pattern if candidate else "NORMAL"

    if pattern == "LAYERED":
        # Columns: SOURCE -> INTERMEDIARY... -> CONVERGENCE
        order = {"SOURCE": 0, "INTERMEDIARY": 1, "CONVERGENCE": 2, "PARTICIPANT": 1}
        columns: Dict[int, List[str]] = {}
        for key in keys:
            col = order.get(roles.get(key, "PARTICIPANT"), 1)
            columns.setdefault(col, []).append(key)
        for col, members in columns.items():
            for i, key in enumerate(members):
                spacing = 140.0
                offset = (i - (len(members) - 1) / 2.0) * spacing
                positions[key] = (col * 320.0, offset)
        return positions

    # Ring layout with the busiest account at the centre
    ranked = sorted(
        keys,
        key=lambda k: snapshot.node_stats.get(k, {}).get("total_in", 0.0)
        + snapshot.node_stats.get(k, {}).get("total_out", 0.0),
        reverse=True,
    )
    hub = ranked[0]
    positions[hub] = (0.0, 0.0)
    others = [k for k in ranked[1:]]
    radius = 180.0 + 12.0 * max(len(others) - 6, 0)
    for i, key in enumerate(others):
        angle = (2 * math.pi * i) / max(len(others), 1)
        positions[key] = (radius * math.cos(angle), radius * math.sin(angle))
    return positions


def _pattern_label(pattern: str, index: int) -> str:
    friendly = {
        "CIRCULAR": "Circular movement cluster",
        "LAYERED": "Layered movement chain",
        "FAN_OUT": "Fan-out dispersion cluster",
        "FAN_IN": "Fan-in convergence cluster",
        "SMURFING": "Structuring / smurfing cluster",
        "PASS_THROUGH": "Pass-through cluster",
        "NORMAL": "Transaction cluster",
    }.get(pattern, "Transaction cluster")
    return f"Suspicious Network #{index} - {friendly}"


def _composite_score(gnn_graph_score: float, structural_score: float) -> float:
    return round(
        min(GNN_WEIGHT * gnn_graph_score + STRUCTURAL_WEIGHT * structural_score * 100.0, 100.0),
        1,
    )


def build_provenance(output: GNNOutput) -> ModelProvenance:
    data = output.provenance()
    return ModelProvenance(
        model_name=data["model_name"],
        model_version=data["model_version"],
        model_type=data["model_type"],
        trained=data["trained"],
        training_data=data["training_data"],
        notes=data["notes"],
    )


def _fingerprint(pattern: str, node_keys: Sequence[str]) -> str:
    """Stable cluster identity: the same typology over the same accounts."""
    payload = pattern + "|" + "|".join(sorted(node_keys))
    return hashlib.sha256(payload.encode()).hexdigest()[:64]


def _next_network_seq(existing: Sequence[Network]) -> int:
    highest = 0
    for network in existing:
        match = re.fullmatch(r"NET-(\d+)", network.network_ref or "")
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _retire_unseen(db: Session, existing: Sequence[Network], seen_ids: set[int]) -> None:
    """Clusters this sweep no longer detects.

    One still referenced by an alert, investigation or assessment is kept (as
    inactive) so that evidence trail stays intact; an unreferenced one is deleted.
    """
    for network in existing:
        if network.id in seen_ids:
            continue
        referenced = any(
            db.scalar(select(model.id).where(model.network_id == network.id).limit(1))
            for model in (Alert, Investigation, RiskAssessment)
        )
        if referenced:
            network.is_active = False
        else:
            db.delete(network)


def analyse_graph(
    db: Session,
    snapshot: Optional[GraphSnapshot] = None,
    persist: bool = True,
    max_networks: int = 40,
) -> List[Network]:
    """Run the full detection sweep and persist suspicious clusters."""
    engine = get_gnn_engine()
    graph = snapshot or graph_builder.build_full_graph(db)
    if graph.num_nodes == 0:
        return []

    # Whole-graph inference gives every account a node score
    global_output = engine.infer(graph)

    # Refresh denormalised account metrics from the graph engine
    for account in db.scalars(select(Account)).all():
        stats = graph.node_stats.get(account.account_ref)
        if not stats:
            continue
        account.total_in = round(stats["total_in"], 2)
        account.total_out = round(stats["total_out"], 2)
        account.degree_in = int(stats["degree_in"])
        account.degree_out = int(stats["degree_out"])
        node_score = global_output.node_scores.get(account.account_ref)
        if node_score is not None:
            account.risk_score = node_score
            account.risk_level = settings.risk_level_for(node_score)

    candidates = merge_candidates(detect_all_patterns(graph))
    candidates = [c for c in candidates if len(c.node_keys) >= MIN_CLUSTER_NODES]
    candidates.sort(key=lambda c: c.structural_score, reverse=True)
    candidates = candidates[:max_networks]

    now = utcnow()
    existing: List[Network] = []
    if persist:
        # Clusters keep a stable identity across sweeps (see `_fingerprint`):
        # a re-detected cluster is updated in place, so its ref, alerts and
        # investigation links survive. Only the derived membership rows and the
        # transaction links are rebuilt from scratch.
        existing = list(db.scalars(select(Network)).all())
        db.execute(delete(NetworkEdge))
        db.execute(delete(NetworkNode))
        db.execute(
            Transaction.__table__.update().values(network_id=None, is_suspicious_edge=False)
        )
        db.flush()
    existing_by_fp = {n.fingerprint: n for n in existing if n.fingerprint}
    next_seq = _next_network_seq(existing)
    seen_ids: set[int] = set()
    seen_fps: set[str] = set()

    networks: List[Network] = []
    account_by_ref = {a.account_ref: a for a in db.scalars(select(Account)).all()}
    txn_by_ref = {t.txn_ref: t for t in db.scalars(select(Transaction)).all()}

    for candidate in candidates:
        sub = graph.subgraph(candidate.node_keys)
        if sub.num_nodes < MIN_CLUSTER_NODES or sub.num_edges == 0:
            continue
        fingerprint = _fingerprint(candidate.pattern, sub.node_keys)
        if fingerprint in seen_fps:
            continue
        seen_fps.add(fingerprint)

        output = engine.infer(sub)
        composite = _composite_score(output.graph_score, candidate.structural_score)
        level = settings.risk_level_for(composite)
        signals = build_network_signals(sub, output, candidate)
        metrics = structural_metrics(sub, candidate)
        positions = _radial_layout(sub, candidate)
        is_suspicious = composite >= SUSPICIOUS_THRESHOLD

        network = existing_by_fp.get(fingerprint)
        if network is None:
            network = Network(
                network_ref=f"NET-{next_seq:04d}",
                label=_pattern_label(candidate.pattern, next_seq),
                fingerprint=fingerprint,
                pattern=candidate.pattern,
                detected_at=now,
            )
            next_seq += 1
        network.node_count = sub.num_nodes
        network.edge_count = sub.num_edges
        network.total_flow = round(sub.total_flow(), 2)
        network.risk_score = composite
        network.risk_level = level
        network.is_suspicious = is_suspicious
        network.is_active = True
        network.last_seen_at = now
        network.model_name = output.engine_name
        network.model_version = output.engine_version
        network.signals = signals
        network.structural_metrics = metrics
        network.summary = candidate.description

        if not persist:
            networks.append(network)
            continue

        db.add(network)
        db.flush()
        seen_ids.add(network.id)

        for key in sub.node_keys:
            account = account_by_ref.get(key)
            if account is None:
                continue
            node_score = output.node_scores.get(key, 0.0)
            x, y = positions.get(key, (0.0, 0.0))
            stats = sub.node_stats.get(key, {})
            db.add(
                NetworkNode(
                    network_id=network.id,
                    account_id=account.id,
                    role=candidate.roles.get(key, "PARTICIPANT"),
                    entity_type=account.entity_type,
                    gnn_node_score=node_score,
                    is_suspicious=node_score >= NODE_FLAG_THRESHOLD,
                    centrality=round(
                        (stats.get("degree_in", 0.0) + stats.get("degree_out", 0.0))
                        / max(sub.num_nodes - 1, 1),
                        4,
                    ),
                    volume=round(
                        stats.get("total_in", 0.0) + stats.get("total_out", 0.0), 2
                    ),
                    layout_x=round(x, 2),
                    layout_y=round(y, 2),
                )
            )

        hop_lookup = {key: i for i, key in enumerate(candidate.edge_keys)}
        for i, edge in enumerate(sub.edges):
            txn = txn_by_ref.get(edge.key)
            source = account_by_ref.get(edge.source)
            target = account_by_ref.get(edge.target)
            if source is None or target is None:
                continue
            edge_score = output.edge_scores.get(edge.key, 0.0)
            flagged = edge_score >= EDGE_FLAG_THRESHOLD
            db.add(
                NetworkEdge(
                    network_id=network.id,
                    transaction_id=txn.id if txn else None,
                    source_account_id=source.id,
                    target_account_id=target.id,
                    amount=edge.amount,
                    txn_type=edge.txn_type,
                    occurred_at=edge.occurred_at,
                    gnn_edge_score=edge_score,
                    is_suspicious=flagged,
                    hop_index=hop_lookup.get(edge.key),
                )
            )
            if txn is not None and is_suspicious:
                txn.network_id = network.id
                txn.is_suspicious_edge = flagged
                # A transaction sitting inside a flagged laundering structure is
                # riskier than its standalone features suggest - that is the whole
                # point of the network layer. Lift its score to the edge score the
                # GNN assigned, but never lower an existing score, and record that
                # the NETWORK layer is what raised it.
                if edge_score > (txn.risk_score or 0.0):
                    txn.risk_score = round(edge_score, 1)
                    txn.risk_level = settings.risk_level_for(edge_score)
                    txn.scored_by = "NETWORK"

        networks.append(network)

    if persist:
        _retire_unseen(db, existing, seen_ids)
    return networks


def raise_network_alerts(db: Session, networks: Sequence[Network]) -> List[Alert]:
    """One alert per suspicious cluster, written in indicator language.

    Returns only newly raised alerts; clusters already alerted are refreshed.
    """
    from app.services import alert_service

    created: List[Alert] = []
    for network in networks:
        if not network.is_suspicious:
            continue

        signal_lines = "; ".join(
            f"{s['label']} (+{s['contribution']})" for s in (network.signals or [])[:5]
        )
        participants = db.scalars(
            select(NetworkNode).where(NetworkNode.network_id == network.id)
        ).all()
        anchor = max(participants, key=lambda n: n.gnn_node_score, default=None)
        engine_kind = (
            "graph neural network" if network.model_name == "aml_gnn" else "analytic graph engine"
        )

        explanation = (
            f"{network.label} was identified as a potential laundering pattern across "
            f"{network.node_count} accounts and {network.edge_count} transactions, with a "
            f"total flow of {network.total_flow:,.2f}. Structural analysis classified the "
            f"topology as {network.pattern}. {network.summary} "
            f"The {engine_kind} scored the cluster at {network.risk_score}/100. "
            f"Contributing signals: {signal_lines}. "
            "These are model-generated risk indicators describing the shape of the "
            "transaction flow. They do not establish that any offence occurred and "
            "require investigation."
        )

        # One live alert per cluster: re-detection refreshes it, and a cluster an
        # analyst has closed is not re-raised for a full review window.
        alert, is_new = alert_service.upsert_alert(
            db,
            dedupe_key=alert_service.dedupe_key_for(
                "NETWORK", network.fingerprint or network.network_ref, "SUSPICIOUS_NETWORK"
            ),
            suppress_after_close=timedelta(days=30),
            source=AlertSource.NETWORK.value,
            alert_type="SUSPICIOUS_NETWORK_DETECTED",
            title=(
                f"Potential laundering pattern requires investigation - "
                f"{network.network_ref} ({network.pattern})"
            ),
            explanation=explanation,
            risk_score=network.risk_score,
            risk_level=network.risk_level,
            network_id=network.id,
            account_id=anchor.account_id if anchor else None,
            rule_code=_rule_code_for(network.pattern),
            evidence={
                "pattern": network.pattern,
                "node_count": network.node_count,
                "edge_count": network.edge_count,
                "total_flow": network.total_flow,
                "signals": network.signals,
                "structural_metrics": network.structural_metrics,
                "layer": "NETWORK (graph + GNN)",
                "engine": network.model_name,
            },
        )
        if is_new and alert is not None:
            created.append(alert)
    return created


def _rule_code_for(pattern: str) -> str:
    return {
        "CIRCULAR": "NETWORK_CIRCULAR_FLOW",
        "LAYERED": "NETWORK_LAYERING",
        "FAN_OUT": "NETWORK_FAN_PATTERN",
        "FAN_IN": "NETWORK_FAN_PATTERN",
        "SMURFING": "NETWORK_FAN_PATTERN",
    }.get(pattern, "NETWORK_LAYERING")


# ---------------------------------------------------------------------------
# Read paths for the investigator graph view
# ---------------------------------------------------------------------------


def _to_graph_node(
    account: Account,
    node_row: Optional[NetworkNode],
    snapshot: Optional[GraphSnapshot] = None,
    gnn_score: Optional[float] = None,
) -> GraphNode:
    stats = (snapshot.node_stats.get(account.account_ref, {}) if snapshot else {}) or {}
    score = (
        gnn_score
        if gnn_score is not None
        else (node_row.gnn_node_score if node_row else account.risk_score)
    )
    return GraphNode(
        id=account.account_ref,
        account_ref=account.account_ref,
        label=account.display_name,
        entity_type=account.entity_type,
        role=node_row.role if node_row else "PARTICIPANT",
        risk_score=account.risk_score,
        risk_level=account.risk_level,
        gnn_node_score=round(score or 0.0, 2),
        is_suspicious=(score or 0.0) >= NODE_FLAG_THRESHOLD,
        volume=round(
            stats.get("total_in", account.total_in or 0.0)
            + stats.get("total_out", account.total_out or 0.0),
            2,
        ),
        total_in=round(stats.get("total_in", account.total_in or 0.0), 2),
        total_out=round(stats.get("total_out", account.total_out or 0.0), 2),
        connections=int(
            stats.get("degree_in", account.degree_in or 0)
            + stats.get("degree_out", account.degree_out or 0)
        ),
        degree_in=int(stats.get("degree_in", account.degree_in or 0)),
        degree_out=int(stats.get("degree_out", account.degree_out or 0)),
        centrality=round(node_row.centrality if node_row else 0.0, 4),
        country=account.country,
        city=account.city,
        institution=account.institution,
        customer_ref=account.customer.customer_ref if account.customer else None,
        x=node_row.layout_x if node_row else 0.0,
        y=node_row.layout_y if node_row else 0.0,
    )


def network_graph(db: Session, network: Network) -> Dict[str, Any]:
    """Nodes + edges + assessment for one persisted cluster."""
    node_rows: Sequence[NetworkNode] = db.scalars(
        select(NetworkNode).where(NetworkNode.network_id == network.id)
    ).all()
    edge_rows: Sequence[NetworkEdge] = db.scalars(
        select(NetworkEdge).where(NetworkEdge.network_id == network.id)
    ).all()

    accounts = {row.account_id: row.account for row in node_rows}
    snapshot = graph_builder.build_network_graph(db, network)

    nodes = [
        _to_graph_node(row.account, row, snapshot, row.gnn_node_score) for row in node_rows
    ]
    edges: List[GraphEdge] = []
    for row in edge_rows:
        source = accounts.get(row.source_account_id) or db.get(Account, row.source_account_id)
        target = accounts.get(row.target_account_id) or db.get(Account, row.target_account_id)
        if source is None or target is None:
            continue
        edges.append(
            GraphEdge(
                id=f"E{row.id}",
                source=source.account_ref,
                target=target.account_ref,
                transaction_ref=row.transaction.txn_ref if row.transaction else None,
                amount=row.amount,
                currency=source.currency,
                txn_type=row.txn_type,
                occurred_at=row.occurred_at,
                risk_score=row.transaction.risk_score if row.transaction else row.gnn_edge_score,
                gnn_edge_score=row.gnn_edge_score,
                is_suspicious=row.is_suspicious,
                hop_index=row.hop_index,
            )
        )

    return {
        "network_ref": network.network_ref,
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "node_count": network.node_count,
            "edge_count": network.edge_count,
            "total_flow": network.total_flow,
            "pattern": network.pattern,
            "risk_score": network.risk_score,
            "risk_level": network.risk_level,
            "suspicious_nodes": sum(1 for n in nodes if n.is_suspicious),
            "suspicious_edges": sum(1 for e in edges if e.is_suspicious),
        },
        "assessment": assessment_for(db, network),
    }


def assessment_for(db: Session, network: Network) -> NetworkAssessment:
    engine = get_gnn_engine()
    node_rows: Sequence[NetworkNode] = db.scalars(
        select(NetworkNode)
        .where(NetworkNode.network_id == network.id)
        .order_by(NetworkNode.gnn_node_score.desc())
        .limit(5)
    ).all()
    edge_rows: Sequence[NetworkEdge] = db.scalars(
        select(NetworkEdge)
        .where(NetworkEdge.network_id == network.id)
        .order_by(NetworkEdge.gnn_edge_score.desc())
        .limit(5)
    ).all()

    return NetworkAssessment(
        network_ref=network.network_ref,
        network_risk=network.risk_score,
        risk_level=network.risk_level,
        pattern=network.pattern,
        signals=[GNNSignal(**s) for s in (network.signals or [])],
        structural_metrics=network.structural_metrics or {},
        provenance=ModelProvenance(
            model_name=engine.name,
            model_version=engine.version,
            model_type=engine.architecture,
            trained=engine.trained,
            training_data=engine.training_data,
            notes=engine.notes,
        ),
        top_nodes=[
            {
                "account_ref": row.account.account_ref,
                "display_name": row.account.display_name,
                "role": row.role,
                "gnn_node_score": row.gnn_node_score,
                "volume": row.volume,
                "entity_type": row.entity_type,
            }
            for row in node_rows
        ],
        top_edges=[
            {
                "transaction_ref": row.transaction.txn_ref if row.transaction else None,
                "amount": row.amount,
                "gnn_edge_score": row.gnn_edge_score,
                "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
                "hop_index": row.hop_index,
            }
            for row in edge_rows
        ],
        disclaimer=NETWORK_DISCLAIMER,
    )


def explore_graph(
    db: Session,
    account_ref: Optional[str] = None,
    hops: int = 2,
    min_risk: float = 0.0,
    min_amount: float = 0.0,
    max_nodes: int = 160,
) -> Dict[str, Any]:
    """Ad-hoc graph exploration for the investigator view."""
    engine = get_gnn_engine()
    if account_ref:
        snapshot = graph_builder.build_neighbourhood_graph(
            db, account_ref, hops=hops, max_nodes=max_nodes
        )
    else:
        # Default view: the union of all suspicious clusters
        suspicious = db.scalars(
            select(Network)
            .where(Network.is_suspicious.is_(True), Network.is_active.is_(True))
            .limit(8)
        ).all()
        keys: List[str] = []
        for network in suspicious:
            rows = db.scalars(
                select(NetworkNode).where(NetworkNode.network_id == network.id)
            ).all()
            keys.extend(row.account.account_ref for row in rows)
        full = graph_builder.build_full_graph(db)
        snapshot = full.subgraph(list(dict.fromkeys(keys))[:max_nodes]) if keys else full

    if snapshot.num_nodes == 0:
        return {"network_ref": None, "nodes": [], "edges": [], "stats": {}, "assessment": None}

    output = engine.infer(snapshot)
    accounts = {
        a.account_ref: a
        for a in db.scalars(
            select(Account).where(Account.account_ref.in_(snapshot.node_keys))
        ).all()
    }
    node_rows = {
        row.account.account_ref: row
        for row in db.scalars(
            select(NetworkNode).join(Account).where(Account.account_ref.in_(snapshot.node_keys))
        ).all()
    }

    nodes: List[GraphNode] = []
    for key in snapshot.node_keys:
        account = accounts.get(key)
        if account is None:
            continue
        score = output.node_scores.get(key, 0.0)
        if score < min_risk:
            continue
        nodes.append(_to_graph_node(account, node_rows.get(key), snapshot, score))

    visible = {n.id for n in nodes}
    txn_by_ref = {
        t.txn_ref: t
        for t in db.scalars(
            select(Transaction).where(Transaction.txn_ref.in_(snapshot.edge_keys))
        ).all()
    }
    edges: List[GraphEdge] = []
    for edge in snapshot.edges:
        if edge.source not in visible or edge.target not in visible:
            continue
        if edge.amount < min_amount:
            continue
        txn = txn_by_ref.get(edge.key)
        score = output.edge_scores.get(edge.key, 0.0)
        edges.append(
            GraphEdge(
                id=edge.key,
                source=edge.source,
                target=edge.target,
                transaction_ref=edge.key,
                amount=edge.amount,
                txn_type=edge.txn_type,
                occurred_at=edge.occurred_at,
                risk_score=txn.risk_score if txn else score,
                gnn_edge_score=round(score, 2),
                is_suspicious=score >= EDGE_FLAG_THRESHOLD,
                hop_index=None,
            )
        )

    return {
        "network_ref": None,
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "total_flow": round(sum(e.amount for e in edges), 2),
            "suspicious_nodes": sum(1 for n in nodes if n.is_suspicious),
            "suspicious_edges": sum(1 for e in edges if e.is_suspicious),
            "engine": engine.name,
            "engine_trained": engine.trained,
            "graph_score": output.graph_score,
        },
        "assessment": None,
    }


def inspect_node(db: Session, account_ref: str, hops: int = 1) -> Dict[str, Any]:
    """Side-panel payload for a selected account."""
    engine = get_gnn_engine()
    account = db.scalar(select(Account).where(Account.account_ref == account_ref))
    if account is None:
        return {}

    snapshot = graph_builder.build_neighbourhood_graph(db, account_ref, hops=hops, max_nodes=60)
    output = engine.infer(snapshot)
    node_row = db.scalar(
        select(NetworkNode).where(NetworkNode.account_id == account.id).limit(1)
    )

    node = _to_graph_node(account, node_row, snapshot, output.node_scores.get(account_ref))
    neighbour_keys = [k for k in snapshot.node_keys if k != account_ref]
    accounts = {
        a.account_ref: a
        for a in db.scalars(
            select(Account).where(Account.account_ref.in_(neighbour_keys))
        ).all()
    }
    neighbours = [
        _to_graph_node(accounts[k], None, snapshot, output.node_scores.get(k))
        for k in neighbour_keys
        if k in accounts
    ]
    neighbours.sort(key=lambda n: n.gnn_node_score, reverse=True)

    edges = [
        GraphEdge(
            id=e.key,
            source=e.source,
            target=e.target,
            transaction_ref=e.key,
            amount=e.amount,
            txn_type=e.txn_type,
            occurred_at=e.occurred_at,
            risk_score=e.risk_score,
            gnn_edge_score=round(output.edge_scores.get(e.key, 0.0), 2),
            is_suspicious=output.edge_scores.get(e.key, 0.0) >= EDGE_FLAG_THRESHOLD,
        )
        for e in snapshot.edges
        if e.source == account_ref or e.target == account_ref
    ]

    signals = build_network_signals(snapshot, output, None)
    memberships = db.scalars(
        select(Network)
        .join(NetworkNode, NetworkNode.network_id == Network.id)
        .where(NetworkNode.account_id == account.id, Network.is_active.is_(True))
    ).all()

    recent = db.scalars(
        select(Transaction)
        .where(
            (Transaction.sender_account_id == account.id)
            | (Transaction.receiver_account_id == account.id)
        )
        .order_by(Transaction.occurred_at.desc())
        .limit(10)
    ).all()

    return {
        "node": node,
        "neighbours": neighbours[:20],
        "edges": edges[:40],
        "gnn_signals": [GNNSignal(**s) for s in signals],
        "networks": [
            {
                "id": n.id,
                "network_ref": n.network_ref,
                "label": n.label,
                "pattern": n.pattern,
                "detected_at": n.detected_at,
                "node_count": n.node_count,
                "edge_count": n.edge_count,
                "total_flow": n.total_flow,
                "risk_score": n.risk_score,
                "risk_level": n.risk_level,
                "is_suspicious": n.is_suspicious,
                "summary": n.summary or "",
            }
            for n in memberships
        ],
        "recent_transactions": [
            {
                "txn_ref": t.txn_ref,
                "occurred_at": t.occurred_at.isoformat(),
                "amount": t.amount,
                "direction": "OUT" if t.sender_account_id == account.id else "IN",
                "channel": t.channel,
                "risk_score": t.risk_score,
                "risk_level": t.risk_level,
            }
            for t in recent
        ],
        "disclaimer": NETWORK_DISCLAIMER,
    }


def suspicious_summary(db: Session, limit: int = 6) -> List[Dict[str, Any]]:
    rows = db.scalars(
        select(Network)
        .where(Network.is_suspicious.is_(True), Network.is_active.is_(True))
        .order_by(Network.risk_score.desc())
        .limit(limit)
    ).all()
    return [
        {
            "network_ref": n.network_ref,
            "label": n.label,
            "pattern": n.pattern,
            "risk_score": n.risk_score,
            "risk_level": n.risk_level,
            "node_count": n.node_count,
            "edge_count": n.edge_count,
            "total_flow": n.total_flow,
            "summary": n.summary or "",
        }
        for n in rows
    ]


def suspicious_count(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count(Network.id)).where(
                Network.is_suspicious.is_(True), Network.is_active.is_(True)
            )
        )
        or 0
    )
