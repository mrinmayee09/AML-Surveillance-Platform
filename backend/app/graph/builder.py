"""Builds `GraphSnapshot` objects from the live database.

This is the inference-side counterpart to `app.graph.synthetic`. Both hand the
same `NodeRecord`/`EdgeRecord` types to `build_snapshot()`, which guarantees the
GNN sees an identically-shaped feature space in production and in training.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.graph.types import EdgeRecord, GraphSnapshot, NodeRecord, build_snapshot
from app.models import Account, Network, NetworkNode, Transaction

# Jurisdictions treated as elevated-risk by this demo configuration.
HIGH_RISK_COUNTRIES = {"Cyprus", "Panama", "Seychelles", "Cayman Islands", "Marshall Islands"}


def _to_node_record(account: Account) -> NodeRecord:
    return NodeRecord(
        key=account.account_ref,
        label=account.display_name,
        entity_type=account.entity_type,
        account_age_days=account.opened_days_ago or 365,
        is_dormant=bool(account.is_dormant),
        balance=float(account.balance or 0.0),
        country=account.country,
        city=account.city,
        institution=account.institution,
        customer_ref=account.customer.customer_ref if account.customer else None,
        db_id=account.id,
    )


def _to_edge_record(txn: Transaction, ref_by_id: Dict[int, str]) -> Optional[EdgeRecord]:
    source = ref_by_id.get(txn.sender_account_id)
    target = ref_by_id.get(txn.receiver_account_id)
    if not source or not target:
        return None
    return EdgeRecord(
        key=txn.txn_ref,
        source=source,
        target=target,
        amount=float(txn.amount),
        occurred_at=txn.occurred_at,
        txn_type=txn.txn_type,
        is_international=bool(txn.is_international),
        db_id=txn.id,
        risk_score=float(txn.risk_score or 0.0),
    )


def build_full_graph(
    db: Session,
    since: Optional[datetime] = None,
    limit_transactions: Optional[int] = 20_000,
) -> GraphSnapshot:
    """Snapshot of the whole transaction graph (optionally time-windowed)."""
    accounts: Sequence[Account] = db.scalars(select(Account)).all()
    ref_by_id = {a.id: a.account_ref for a in accounts}

    stmt = select(Transaction).order_by(Transaction.occurred_at.desc())
    if since is not None:
        stmt = stmt.where(Transaction.occurred_at >= since)
    if limit_transactions:
        stmt = stmt.limit(limit_transactions)

    transactions: Sequence[Transaction] = db.scalars(stmt).all()

    nodes = [_to_node_record(a) for a in accounts]
    edges = [
        record
        for record in (_to_edge_record(t, ref_by_id) for t in transactions)
        if record is not None
    ]
    return build_snapshot(nodes, edges)


def build_neighbourhood_graph(
    db: Session, account_ref: str, hops: int = 2, max_nodes: int = 160
) -> GraphSnapshot:
    """Breadth-first `hops`-hop neighbourhood around one account.

    Used by the investigator graph view so a single account can be expanded
    without materialising the entire institution's graph.
    """
    accounts: Sequence[Account] = db.scalars(select(Account)).all()
    by_ref = {a.account_ref: a for a in accounts}
    ref_by_id = {a.id: a.account_ref for a in accounts}
    if account_ref not in by_ref:
        return build_snapshot([], [])

    transactions: Sequence[Transaction] = db.scalars(select(Transaction)).all()
    adjacency: Dict[str, set] = {ref: set() for ref in by_ref}
    edge_records: List[EdgeRecord] = []
    for txn in transactions:
        record = _to_edge_record(txn, ref_by_id)
        if record is None:
            continue
        edge_records.append(record)
        adjacency[record.source].add(record.target)
        adjacency[record.target].add(record.source)

    # BFS outward from the seed account
    frontier = {account_ref}
    visited = {account_ref}
    for _ in range(max(hops, 0)):
        nxt: set = set()
        for node in frontier:
            for neighbour in adjacency.get(node, ()):
                if neighbour not in visited and len(visited) < max_nodes:
                    visited.add(neighbour)
                    nxt.add(neighbour)
        frontier = nxt
        if not frontier:
            break

    nodes = [_to_node_record(by_ref[ref]) for ref in visited if ref in by_ref]
    edges = [e for e in edge_records if e.source in visited and e.target in visited]
    return build_snapshot(nodes, edges)


def build_network_graph(db: Session, network: Network) -> GraphSnapshot:
    """Snapshot of exactly the accounts belonging to one persisted cluster."""
    node_rows: Sequence[NetworkNode] = db.scalars(
        select(NetworkNode).where(NetworkNode.network_id == network.id)
    ).all()
    account_ids = [row.account_id for row in node_rows]
    if not account_ids:
        return build_snapshot([], [])

    accounts: Sequence[Account] = db.scalars(
        select(Account).where(Account.id.in_(account_ids))
    ).all()
    ref_by_id = {a.id: a.account_ref for a in accounts}
    refs = set(ref_by_id.values())

    transactions: Sequence[Transaction] = db.scalars(
        select(Transaction).where(
            Transaction.sender_account_id.in_(account_ids),
            Transaction.receiver_account_id.in_(account_ids),
        )
    ).all()

    nodes = [_to_node_record(a) for a in accounts]
    edges = [
        record
        for record in (_to_edge_record(t, ref_by_id) for t in transactions)
        if record is not None and record.source in refs and record.target in refs
    ]
    return build_snapshot(nodes, edges)


def build_customer_graph(
    db: Session, customer_ref: str, window_days: int = 90, max_nodes: int = 120
) -> GraphSnapshot:
    """Graph of a customer's own accounts plus their direct counterparties."""
    from app.models import Customer

    customer = db.scalar(select(Customer).where(Customer.customer_ref == customer_ref))
    if customer is None:
        return build_snapshot([], [])

    own_ids = [a.id for a in customer.accounts]
    if not own_ids:
        return build_snapshot([], [])

    since = datetime.utcnow() - timedelta(days=window_days)
    transactions: Sequence[Transaction] = db.scalars(
        select(Transaction).where(
            Transaction.occurred_at >= since,
            (Transaction.sender_account_id.in_(own_ids))
            | (Transaction.receiver_account_id.in_(own_ids)),
        )
    ).all()

    touched = set(own_ids)
    for txn in transactions:
        touched.add(txn.sender_account_id)
        touched.add(txn.receiver_account_id)
        if len(touched) >= max_nodes:
            break

    accounts: Sequence[Account] = db.scalars(
        select(Account).where(Account.id.in_(list(touched)))
    ).all()
    ref_by_id = {a.id: a.account_ref for a in accounts}
    refs = set(ref_by_id.values())

    nodes = [_to_node_record(a) for a in accounts]
    edges = [
        record
        for record in (_to_edge_record(t, ref_by_id) for t in transactions)
        if record is not None and record.source in refs and record.target in refs
    ]
    return build_snapshot(nodes, edges)


def is_high_risk_country(country: str) -> bool:
    return country in HIGH_RISK_COUNTRIES


def refresh_account_metrics(db: Session, snapshot: GraphSnapshot) -> int:
    """Write the graph engine's aggregates back onto the accounts table."""
    accounts: Iterable[Account] = db.scalars(select(Account)).all()
    updated = 0
    for account in accounts:
        stats = snapshot.node_stats.get(account.account_ref)
        if not stats:
            continue
        account.total_in = round(stats["total_in"], 2)
        account.total_out = round(stats["total_out"], 2)
        account.degree_in = int(stats["degree_in"])
        account.degree_out = int(stats["degree_out"])
        updated += 1
    return updated
