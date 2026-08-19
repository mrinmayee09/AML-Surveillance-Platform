"""Persisted graph subgraphs produced by the graph engine + GNN.

`Network` is a candidate suspicious cluster. `NetworkNode` / `NetworkEdge` are
the materialised projection served to the investigator graph view, carrying the
per-node and per-edge scores emitted by the GNN heads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base_mixins import TimestampMixin


class Network(Base, TimestampMixin):
    __tablename__ = "networks"

    id: Mapped[int] = mapped_column(primary_key=True)
    network_ref: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(128))
    # CIRCULAR | LAYERED | FAN_OUT | FAN_IN | SMURFING | PASS_THROUGH | NORMAL
    pattern: Mapped[str] = mapped_column(String(24), default="NORMAL", index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    node_count: Mapped[int] = mapped_column(Integer, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, default=0)
    total_flow: Mapped[float] = mapped_column(Float, default=0.0)

    risk_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW", index=True)
    is_suspicious: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Provenance + explanation of the network score
    model_name: Mapped[str] = mapped_column(String(64), default="aml_gnn")
    model_version: Mapped[str] = mapped_column(String(24), default="0.1.0")
    signals: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON, default=list)
    structural_metrics: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, default=dict)
    summary: Mapped[Optional[str]] = mapped_column(Text, default="")

    nodes: Mapped[List["NetworkNode"]] = relationship(
        "NetworkNode", back_populates="network", cascade="all, delete-orphan"
    )
    edges: Mapped[List["NetworkEdge"]] = relationship(
        "NetworkEdge", back_populates="network", cascade="all, delete-orphan"
    )
    alerts: Mapped[List["Alert"]] = relationship("Alert", back_populates="network")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Network {self.network_ref} {self.pattern} {self.risk_score}>"


class NetworkNode(Base, TimestampMixin):
    __tablename__ = "network_nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    network_id: Mapped[int] = mapped_column(
        ForeignKey("networks.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)

    role: Mapped[str] = mapped_column(String(24), default="PARTICIPANT")
    entity_type: Mapped[str] = mapped_column(String(24), default="ACCOUNT")
    # GNN node-classification head output (0-100)
    gnn_node_score: Mapped[float] = mapped_column(Float, default=0.0)
    is_suspicious: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    centrality: Mapped[float] = mapped_column(Float, default=0.0)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    layout_x: Mapped[float] = mapped_column(Float, default=0.0)
    layout_y: Mapped[float] = mapped_column(Float, default=0.0)

    network: Mapped["Network"] = relationship("Network", back_populates="nodes")
    account: Mapped["Account"] = relationship("Account")


class NetworkEdge(Base, TimestampMixin):
    __tablename__ = "network_edges"

    id: Mapped[int] = mapped_column(primary_key=True)
    network_id: Mapped[int] = mapped_column(
        ForeignKey("networks.id", ondelete="CASCADE"), index=True
    )
    transaction_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("transactions.id"), nullable=True, index=True
    )
    source_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    target_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))

    amount: Mapped[float] = mapped_column(Float, default=0.0)
    txn_type: Mapped[str] = mapped_column(String(16), default="TRANSFER")
    occurred_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # GNN edge-scoring head output (0-100)
    gnn_edge_score: Mapped[float] = mapped_column(Float, default=0.0)
    is_suspicious: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Sequence position within a detected layering chain, when applicable
    hop_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    network: Mapped["Network"] = relationship("Network", back_populates="edges")
    transaction: Mapped[Optional["Transaction"]] = relationship("Transaction")
