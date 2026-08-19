"""Graph / GNN schemas served to the investigator network view."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.schemas.common import ModelProvenance


class GraphNode(BaseModel):
    id: str
    account_ref: str
    label: str
    entity_type: str
    role: str
    risk_score: float
    risk_level: str
    gnn_node_score: float
    is_suspicious: bool
    volume: float
    total_in: float
    total_out: float
    connections: int
    degree_in: int
    degree_out: int
    centrality: float
    country: str
    city: str
    institution: str
    customer_ref: Optional[str] = None
    x: float = 0.0
    y: float = 0.0


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    transaction_ref: Optional[str] = None
    amount: float
    currency: str = "INR"
    txn_type: str
    occurred_at: Optional[datetime] = None
    risk_score: float
    gnn_edge_score: float
    is_suspicious: bool
    hop_index: Optional[int] = None


class GNNSignal(BaseModel):
    code: str
    label: str
    contribution: float
    detail: str = ""


class NetworkListItem(BaseModel):
    id: int
    network_ref: str
    label: str
    pattern: str
    detected_at: datetime
    node_count: int
    edge_count: int
    total_flow: float
    risk_score: float
    risk_level: str
    is_suspicious: bool
    summary: str = ""


class NetworkAssessment(BaseModel):
    """GNN output for one candidate cluster, with honest provenance."""

    network_ref: str
    network_risk: float
    risk_level: str
    pattern: str
    signals: List[GNNSignal]
    structural_metrics: Dict[str, Any]
    provenance: ModelProvenance
    top_nodes: List[Dict[str, Any]] = []
    top_edges: List[Dict[str, Any]] = []
    # Mandatory framing: indicators, not proof
    disclaimer: str


class NetworkDetail(NetworkListItem):
    assessment: NetworkAssessment
    participants: List[Dict[str, Any]] = []


class NetworkGraphResponse(BaseModel):
    network_ref: Optional[str] = None
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    stats: Dict[str, Any]
    assessment: Optional[NetworkAssessment] = None


class NodeInspection(BaseModel):
    node: GraphNode
    neighbours: List[GraphNode]
    edges: List[GraphEdge]
    gnn_signals: List[GNNSignal]
    networks: List[NetworkListItem]
    recent_transactions: List[Dict[str, Any]]
    disclaimer: str
