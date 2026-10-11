"""Graph / GNN network investigation endpoints."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_actor, get_current_user, require_alerts_update
from app.db.base import get_db
from app.models import Network, NetworkNode, User
from app.schemas.common import Page
from app.schemas.network import (
    NetworkAssessment,
    NetworkDetail,
    NetworkGraphResponse,
    NetworkListItem,
    NodeInspection,
)
from app.services import audit_service, gnn_v2_service, network_service
from app.services.audit_service import Actor

router = APIRouter(prefix="/networks", tags=["networks"])


def _load(db: Session, network_ref: str) -> Network:
    network = db.scalar(select(Network).where(Network.network_ref == network_ref))
    if network is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"No network {network_ref}."},
        )
    return network


def _to_list_item(network: Network) -> NetworkListItem:
    return NetworkListItem(
        id=network.id,
        network_ref=network.network_ref,
        label=network.label,
        pattern=network.pattern,
        detected_at=network.detected_at,
        node_count=network.node_count,
        edge_count=network.edge_count,
        total_flow=network.total_flow,
        risk_score=network.risk_score,
        risk_level=network.risk_level,
        is_suspicious=network.is_suspicious,
        summary=network.summary or "",
    )


@router.get("", response_model=Page[NetworkListItem])
def list_networks(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    pattern: Optional[str] = None,
    risk_level: Optional[str] = Query(None, pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$"),
    suspicious_only: bool = False,
    min_risk: float = Query(0.0, ge=0, le=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    stmt = select(Network)
    count_stmt = select(func.count(Network.id))
    # Clusters a later sweep no longer detects stay reachable by ref (alerts and
    # cases link to them) but drop out of the list.
    conditions = [Network.is_active.is_(True)]

    if pattern:
        conditions.append(Network.pattern == pattern.upper())
    if risk_level:
        conditions.append(Network.risk_level == risk_level)
    if suspicious_only:
        conditions.append(Network.is_suspicious.is_(True))
    if min_risk > 0:
        conditions.append(Network.risk_score >= min_risk)

    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = int(db.scalar(count_stmt) or 0)
    rows = db.scalars(
        stmt.order_by(Network.risk_score.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return Page[NetworkListItem](
        items=[_to_list_item(n) for n in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=max((total + page_size - 1) // page_size, 1),
    )


@router.get("/graph", response_model=NetworkGraphResponse)
def explore_graph(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    account_ref: Optional[str] = Query(None, description="Centre the view on one account"),
    hops: int = Query(2, ge=1, le=3),
    min_risk: float = Query(0.0, ge=0, le=100),
    min_amount: float = Query(0.0, ge=0),
    max_nodes: int = Query(160, ge=10, le=400),
):
    """Ad-hoc graph exploration.

    With no `account_ref`, returns the union of the flagged clusters. With one,
    returns that account's n-hop neighbourhood.
    """
    payload = network_service.explore_graph(
        db,
        account_ref=account_ref,
        hops=hops,
        min_risk=min_risk,
        min_amount=min_amount,
        max_nodes=max_nodes,
    )
    return NetworkGraphResponse(**payload)


@router.get("/node/{account_ref}", response_model=NodeInspection)
def inspect_node(
    account_ref: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    hops: int = Query(1, ge=1, le=2),
):
    """Side-panel detail for a selected account."""
    payload = network_service.inspect_node(db, account_ref, hops=hops)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"No account {account_ref}."},
        )
    return NodeInspection(**payload)


@router.post("/analyse")
def run_analysis(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _: User = Depends(require_alerts_update),
    raise_alerts: bool = Query(True),
):
    """Rebuild the graph, re-run detection + GNN inference, and persist clusters."""
    networks = network_service.analyse_graph(db, persist=True)
    db.flush()
    alerts = network_service.raise_network_alerts(db, networks) if raise_alerts else []

    from app.gnn.registry import get_gnn_engine

    engine = get_gnn_engine()
    audit_service.record(
        db,
        actor,
        action="NETWORK_ANALYSIS_RUN",
        resource_type="SYSTEM",
        resource_ref="GRAPH",
        new_state=f"{len(networks)} clusters",
        detail=(
            f"Graph rebuilt; {len(networks)} cluster(s) detected, "
            f"{sum(1 for n in networks if n.is_suspicious)} flagged suspicious, "
            f"{len(alerts)} alert(s) raised. Engine: {engine.name} "
            f"(trained={engine.trained})."
        ),
    )
    db.commit()

    return {
        "clusters_detected": len(networks),
        "clusters_suspicious": sum(1 for n in networks if n.is_suspicious),
        "alerts_created": len(alerts),
        "alert_refs": [a.alert_ref for a in alerts],
        "engine": {
            "name": engine.name,
            "version": engine.version,
            "architecture": engine.architecture,
            "trained": engine.trained,
        },
    }


# ---------------------------------------------------------------------------
# Window GNN (GraphSAGE trained on IBM AMLworld). Declared before the
# /{network_ref} routes so "gnn" is never read as a network ref.
# ---------------------------------------------------------------------------


@router.get("/gnn/status")
def gnn_status(_: User = Depends(get_current_user)):
    """Is the trained window GNN available, and how did it score on AMLworld?"""
    return gnn_v2_service.status()


@router.post("/gnn/score")
def gnn_score(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _: User = Depends(require_alerts_update),
    hours: int = Query(24, ge=1, le=24 * 7),
):
    """Score every account active in the last `hours` of settled activity."""
    if not gnn_v2_service.status()["available"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "model_unavailable", "message": "The window GNN has not been trained yet."},
        )
    result = gnn_v2_service.score_recent(db, hours=hours)
    audit_service.record(
        db,
        actor,
        action="GNN_SCORING_RUN",
        resource_type="SYSTEM",
        resource_ref="GNN_V2",
        new_state=f"{result['scored']} scored, {result['flagged']} flagged",
        detail=f"Window GNN scored {result['scored']} account(s) active in the {hours}h before "
        f"{result['window_end']}; {result['flagged']} above threshold.",
    )
    db.commit()
    return result


@router.get("/gnn/accounts/{account_ref}")
def gnn_account(
    account_ref: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Latest GNN score and explanation for one account (scored on demand if needed)."""
    row = gnn_v2_service.latest_for(db, account_ref)
    if row is None and gnn_v2_service.status()["available"]:
        rows = gnn_v2_service.score_accounts(db, [account_ref], raise_alerts=False)
        db.commit()
        row = rows[0] if rows else None
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_scored", "message": f"No GNN score for {account_ref}."},
        )
    return gnn_v2_service.to_dict(row)


@router.get("/{network_ref}", response_model=NetworkDetail)
def get_network(
    network_ref: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    network = _load(db, network_ref)
    rows = db.scalars(
        select(NetworkNode)
        .where(NetworkNode.network_id == network.id)
        .order_by(NetworkNode.gnn_node_score.desc())
    ).all()

    return NetworkDetail(
        **_to_list_item(network).model_dump(),
        assessment=network_service.assessment_for(db, network),
        participants=[
            {
                "account_ref": row.account.account_ref,
                "display_name": row.account.display_name,
                "entity_type": row.entity_type,
                "role": row.role,
                "gnn_node_score": row.gnn_node_score,
                "is_suspicious": row.is_suspicious,
                "volume": row.volume,
                "centrality": row.centrality,
                "customer_ref": (
                    row.account.customer.customer_ref if row.account.customer else None
                ),
                "country": row.account.country,
            }
            for row in rows
        ],
    )


@router.get("/{network_ref}/graph", response_model=NetworkGraphResponse)
def get_network_graph(
    network_ref: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Nodes, edges and GNN assessment for one cluster - the Investigate view."""
    network = _load(db, network_ref)
    return NetworkGraphResponse(**network_service.network_graph(db, network))


@router.get("/{network_ref}/assessment", response_model=NetworkAssessment)
def get_network_assessment(
    network_ref: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """GNN risk assessment and contributing signals for one cluster."""
    network = _load(db, network_ref)
    return network_service.assessment_for(db, network)
