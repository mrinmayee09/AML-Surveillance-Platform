"""R4: "which transfers made the model flag this account?"

Occlusion, the same idea the proactive layer uses for its Random Forest: take a
transfer out of the neighbourhood, score the account again, and see how much the
score falls. The transfers whose removal lowers the score most are the ones the
model's decision rests on.

Details
-------
* Candidates are the transfers the seed account could plausibly have been
  influenced through: those touching the seed or one of its direct
  counterparties, largest first, capped (default 60) to keep it fast.
* All "one transfer removed" copies of the window go through the model in ONE
  batched forward pass (copy 0 is the untouched window), so explaining an
  account costs a single model call.
* Removing a transfer removes it from message passing. Node features (window
  statistics such as total inflow) are left as they were, so the explanation
  answers "which connections did the GNN use", not "what if this payment never
  happened". The fidelity test below checks the explanations are faithful.

Fidelity (deletion test)
------------------------
For a flagged account, delete its top-k transfers and measure the score drop;
compare with deleting k transfers chosen at random from the same candidates.
Faithful explanations make the top-k drop clearly larger.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np


@dataclass
class TransferAttribution:
    edge: int  # index into the window's edges
    score_drop: float  # probability points (0-1) lost when the transfer is removed
    rank: int


def candidate_edges(edge_index: np.ndarray, edge_attr: np.ndarray, max_candidates: int = 60) -> np.ndarray:
    """Edges touching the seed (node 0) or one of its direct counterparties."""
    src, dst = edge_index
    if src.size == 0:
        return np.zeros(0, dtype=np.int64)
    direct = set(dst[src == 0].tolist()) | set(src[dst == 0].tolist()) | {0}
    mask = np.isin(src, list(direct)) | np.isin(dst, list(direct))
    idx = np.flatnonzero(mask)
    # Largest transfers first (edge feature 0 is the log-scaled amount)
    order = np.argsort(-edge_attr[idx, 0], kind="stable")
    return idx[order][:max_candidates]


def _batched_scores(model, x: np.ndarray, edge_index: np.ndarray, edge_attr: np.ndarray,
                    removals: Sequence[np.ndarray]) -> np.ndarray:
    """Seed probability for the window with each set of edges removed (one pass)."""
    import torch

    device = next(model.parameters()).device
    n = x.shape[0]
    xs, eis, eas, seeds = [], [], [], []
    for k, removed in enumerate(removals):
        keep = np.ones(edge_index.shape[1], dtype=bool)
        keep[removed] = False
        xs.append(x)
        eis.append(edge_index[:, keep].astype(np.int64) + k * n)
        eas.append(edge_attr[keep])
        seeds.append(k * n)
    with torch.no_grad():
        logits, *_ = model(
            torch.from_numpy(np.concatenate(xs)).to(device),
            torch.from_numpy(np.concatenate(eis, axis=1)).to(device),
            torch.from_numpy(np.concatenate(eas)).to(device),
        )
        return torch.sigmoid(logits[torch.as_tensor(seeds, device=device)]).cpu().numpy()


def explain(model, x: np.ndarray, edge_index: np.ndarray, edge_attr: np.ndarray,
            top_k: int = 5, max_candidates: int = 60) -> Dict[str, object]:
    """Score the seed account and rank the transfers its score depends on."""
    model.eval()
    candidates = candidate_edges(edge_index, edge_attr, max_candidates)
    removals = [np.zeros(0, dtype=np.int64)] + [np.asarray([e]) for e in candidates]
    scores = _batched_scores(model, x, edge_index, edge_attr, removals)
    base, drops = float(scores[0]), scores[0] - scores[1:]
    order = np.argsort(-drops, kind="stable")[:top_k]
    top = [
        TransferAttribution(edge=int(candidates[i]), score_drop=float(drops[i]), rank=r + 1)
        for r, i in enumerate(order)
        if drops[i] > 0
    ]
    return {"score": base, "top": top, "candidates": int(candidates.size)}


def deletion_test(model, x, edge_index, edge_attr, k: int = 3, random_draws: int = 5,
                  rng: Optional[np.random.Generator] = None) -> Optional[Dict[str, float]]:
    """Score drop from deleting the top-k explained transfers vs k random candidates."""
    rng = rng or np.random.default_rng(0)
    result = explain(model, x, edge_index, edge_attr, top_k=k)
    candidates = candidate_edges(edge_index, edge_attr)
    if candidates.size <= k or not result["top"]:
        return None
    top = np.asarray([a.edge for a in result["top"]])
    draws = [rng.choice(candidates, size=len(top), replace=False) for _ in range(random_draws)]
    scores = _batched_scores(
        model, x, edge_index, edge_attr, [np.zeros(0, dtype=np.int64), top, *draws]
    )
    return {
        "base": float(scores[0]),
        "top_k_drop": float(scores[0] - scores[1]),
        "random_k_drop": float(np.mean(scores[0] - scores[2:])),
    }
