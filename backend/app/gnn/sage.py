"""GraphSAGE variants for the R3 ablation.

GraphSAGE (Hamilton et al., 2017) in one sentence: every account updates its
representation by combining its own features with an aggregate of its
neighbours' representations, repeated once per layer. It is *inductive* - it
learns a rule, not one embedding per account - so it scores accounts it never
saw in training, which a payment system with new accounts every day needs.

Three variants, each adding ONE idea, so the ablation measures each idea alone:

  A  plain     classic GraphSAGE: neighbours in both directions pooled together
               with a plain mean. Direction and amounts are ignored.
  B  directed  incoming and outgoing neighbours aggregated separately, weighted
               by transfer amount ("who paid me" != "who I paid"). This is
               `app.gnn.torch_gnn.AmlGNN`, the model R2 trains.
  C  edge      B, plus every message carries the transfer's details (amount,
               timing relative to earlier receipts, payment rail, cross-bank...),
               so a fast relay through a fresh account sends a different message
               from a slow, ordinary payment.

All variants share the same input projection, depth, width and node head, and
return the same tuple as `AmlGNN`, so the training loop treats them alike.
"""

from __future__ import annotations

from typing import Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

from app.gnn.torch_gnn import AmlGNN, _scatter_mean

VARIANTS = ("plain", "directed", "edge")


class PlainSAGELayer(nn.Module):
    """Classic GraphSAGE mean aggregator on the undirected graph."""

    def __init__(self, dim: int):
        super().__init__()
        self.lin_self = nn.Linear(dim, dim)
        self.lin_neigh = nn.Linear(dim, dim)
        self.norm = nn.LayerNorm(dim)

    def forward(self, x, edge_index, edge_attr):
        n = x.size(0)
        if edge_index.numel() == 0:
            return self.norm(F.relu(self.lin_self(x)))
        src, dst = edge_index[0], edge_index[1]
        # Treat every transfer as a two-way link
        a = torch.cat([src, dst])
        b = torch.cat([dst, src])
        neigh = _scatter_mean(x[a], b, n)
        return self.norm(F.relu(self.lin_self(x) + self.lin_neigh(neigh)))


class EdgeSAGELayer(nn.Module):
    """Directed GraphSAGE whose messages are built from neighbour AND transfer."""

    def __init__(self, dim: int, edge_dim: int):
        super().__init__()
        self.lin_self = nn.Linear(dim, dim)
        self.msg_in = nn.Linear(dim + edge_dim, dim)
        self.msg_out = nn.Linear(dim + edge_dim, dim)
        self.norm = nn.LayerNorm(dim)

    def forward(self, x, edge_index, edge_attr):
        n = x.size(0)
        if edge_index.numel() == 0:
            return self.norm(F.relu(self.lin_self(x)))
        src, dst = edge_index[0], edge_index[1]
        # Money arriving at dst from src, described by who sent it and how
        inbound = _scatter_mean(F.relu(self.msg_in(torch.cat([x[src], edge_attr], 1))), dst, n)
        # Money leaving src for dst, described by who received it and how
        outbound = _scatter_mean(F.relu(self.msg_out(torch.cat([x[dst], edge_attr], 1))), src, n)
        return self.norm(F.relu(self.lin_self(x) + inbound + outbound))


class SageVariantGNN(nn.Module):
    """Variant A or C, with the same shape and node head as `AmlGNN` (variant B)."""

    def __init__(
        self,
        variant: str,
        node_dim: int,
        edge_dim: int,
        hidden: int = 64,
        layers: int = 3,
        dropout: float = 0.15,
    ):
        super().__init__()
        if variant not in ("plain", "edge"):
            raise ValueError(f"variant must be 'plain' or 'edge' (B is AmlGNN), got {variant!r}")
        self.variant = variant
        self.input_proj = nn.Linear(node_dim, hidden)
        self.convs = nn.ModuleList(
            [
                PlainSAGELayer(hidden) if variant == "plain" else EdgeSAGELayer(hidden, edge_dim)
                for _ in range(layers)
            ]
        )
        self.dropout = nn.Dropout(dropout)
        self.node_head = nn.Sequential(
            nn.Linear(hidden, 32), nn.ReLU(), nn.Dropout(dropout), nn.Linear(32, 1)
        )

    def forward(self, x, edge_index, edge_attr) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        h = F.relu(self.input_proj(x))
        for conv in self.convs:
            h = self.dropout(conv(h, edge_index, edge_attr))
        node_logits = self.node_head(h).squeeze(-1)
        empty = torch.zeros(0, device=x.device)
        return node_logits, empty, torch.zeros((), device=x.device), h


def build_model(variant: str, node_dim: int, edge_dim: int, hidden: int, layers: int, dropout: float):
    """Construct any of the three variants (B is the original `AmlGNN`)."""
    if variant == "directed":
        return AmlGNN(node_dim=node_dim, edge_dim=edge_dim, hidden=hidden, layers=layers, dropout=dropout)
    return SageVariantGNN(variant, node_dim, edge_dim, hidden=hidden, layers=layers, dropout=dropout)


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
