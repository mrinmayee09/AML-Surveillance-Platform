"""Synthetic transaction-graph generator used to TRAIN the GNN.

Why this exists
---------------
A GNN needs labelled graphs. Real labels (confirmed laundering networks) are not
available to a prototype, but *structural* labels are obtainable honestly: if we
generate a graph and inject a layering chain into it ourselves, we know exactly
which nodes and edges belong to that chain. The GNN is then trained on real
supervised signal - it just learns to recognise topologies-by-construction
rather than adjudicated criminal cases.

The generator deliberately includes benign structures that *mimic* the
suspicious ones (a merchant collecting from many payers looks like smurfing; a
payroll run looks like fan-out dispersion). They differ in amount uniformity,
relay speed and pass-through ratio - the signals the GNN must actually learn.
Without these hard negatives the model would degenerate into a degree counter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Sequence, Set, Tuple

import numpy as np

from app.graph.types import EdgeRecord, GraphSnapshot, NodeRecord, build_snapshot

BASE_TIME = datetime(2026, 1, 6, 9, 0, 0)

SUSPICIOUS_TOPOLOGIES = ("LAYERED", "CIRCULAR", "SMURFING", "FAN_OUT_DISPERSION")
BENIGN_TOPOLOGIES = ("RETAIL_SPOKE", "MERCHANT_COLLECTION", "PAYROLL_FANOUT", "SME_TRADE")

# Class-overlap controls. Without these the synthetic task is trivially separable
# and held-out metrics come out near 1.0 - impressive-looking and useless. These
# rates force the distributions to overlap so the reported numbers mean something.
AMBIGUOUS_BENIGN_RATE = 0.35  # benign structures that mimic laundering signatures
# The three benign topologies whose ambiguous variants are genuine look-alikes.
# RETAIL_SPOKE has no suspicious analogue, so it is excluded from forced mimics.
MIMIC_TOPOLOGIES = ("MERCHANT_COLLECTION", "PAYROLL_FANOUT", "SME_TRADE")
SUBTLE_SUSPICIOUS_RATE = 0.35  # laundering structures that mimic benign behaviour
# Fraction of nodes inside a flagged structure left UNlabelled, mirroring the
# incomplete labelling of real AML investigations.
NODE_LABEL_DROPOUT = 0.10


@dataclass
class LabelledGraph:
    """A generated graph plus its structural ground truth."""

    snapshot: GraphSnapshot
    node_labels: np.ndarray  # (N,) 1 = part of an injected laundering structure
    edge_labels: np.ndarray  # (E,)
    graph_label: int
    topologies: List[str] = field(default_factory=list)


class _Builder:
    """Accumulates nodes/edges while tracking which are part of a typology."""

    def __init__(self, rng: np.random.Generator, prefix: str):
        self.rng = rng
        self.prefix = prefix
        self.nodes: List[NodeRecord] = []
        self.edges: List[EdgeRecord] = []
        self.suspicious_nodes: Set[str] = set()
        self.suspicious_edges: Set[str] = set()
        self._n = 0
        self._e = 0

    def node(
        self,
        entity_type: str = "ACCOUNT",
        age_days: int | None = None,
        dormant: bool = False,
        international: bool = False,
    ) -> str:
        self._n += 1
        key = f"{self.prefix}-N{self._n:03d}"
        self.nodes.append(
            NodeRecord(
                key=key,
                label=key,
                entity_type=entity_type,
                account_age_days=int(
                    age_days if age_days is not None else self.rng.integers(200, 3600)
                ),
                is_dormant=dormant,
                balance=float(self.rng.uniform(5_000, 500_000)),
                country="Singapore" if international else "India",
            )
        )
        return key

    def edge(
        self,
        source: str,
        target: str,
        amount: float,
        at: datetime,
        suspicious: bool,
        international: bool = False,
        txn_type: str = "TRANSFER",
    ) -> str:
        self._e += 1
        key = f"{self.prefix}-E{self._e:04d}"
        self.edges.append(
            EdgeRecord(
                key=key,
                source=source,
                target=target,
                amount=round(float(amount), 2),
                occurred_at=at,
                txn_type=txn_type,
                is_international=international,
            )
        )
        if suspicious:
            self.suspicious_edges.add(key)
            self.suspicious_nodes.update({source, target})
        return key


# ---------------------------------------------------------------------------
# Suspicious topologies
# ---------------------------------------------------------------------------


def _inject_layering(b: _Builder, t0: datetime, subtle: bool = False) -> None:
    """source -> N pass-through intermediaries -> convergence account.

    `subtle=True` produces a harder positive: fewer hops, a fatter skim at each
    hop, and hours rather than minutes between transfers - overlapping with
    legitimate trade chains.
    """
    depth = int(b.rng.integers(3, 4 if subtle else 6))
    principal = float(b.rng.uniform(800_000, 6_000_000))
    source = b.node(age_days=int(b.rng.integers(600, 3000)))
    age_range = (120, 900) if subtle else (20, 260)
    chain = [b.node(age_days=int(b.rng.integers(*age_range))) for _ in range(depth)]
    sink = b.node(age_days=int(b.rng.integers(30, 400)))

    at = t0
    amount = principal
    prev = source
    for hop in chain:
        b.edge(prev, hop, amount, at, suspicious=True)
        # Skim per hop: thin when blatant, fat enough to blur into trade when subtle
        skim = b.rng.uniform(0.10, 0.28) if subtle else b.rng.uniform(0.005, 0.03)
        amount *= 1.0 - float(skim)
        gap = (
            timedelta(hours=float(b.rng.uniform(3, 30)))
            if subtle
            else timedelta(minutes=int(b.rng.integers(2, 55)))
        )
        at += gap
        prev = hop
    b.edge(prev, sink, amount, at, suspicious=True)

    # Some chains split at one hop into two parallel legs, then reconverge
    if depth >= 4 and not subtle and b.rng.random() < 0.55:
        branch = b.node(age_days=int(b.rng.integers(20, 200)))
        split_from = chain[1]
        leg = amount * float(b.rng.uniform(0.3, 0.48))
        b.edge(split_from, branch, leg, at + timedelta(minutes=6), suspicious=True)
        b.edge(branch, sink, leg * 0.985, at + timedelta(minutes=22), suspicious=True)


def _inject_circular(b: _Builder, t0: datetime, subtle: bool = False) -> None:
    """A closed loop returning most of the principal to its origin."""
    size = int(b.rng.integers(3, 7))
    age_range = (400, 2400) if subtle else (60, 900)
    ring = [b.node(age_days=int(b.rng.integers(*age_range))) for _ in range(size)]
    amount = float(b.rng.uniform(500_000, 4_000_000))
    at = t0
    for i in range(size):
        src, dst = ring[i], ring[(i + 1) % size]
        b.edge(src, dst, amount, at, suspicious=True)
        skim = b.rng.uniform(0.08, 0.22) if subtle else b.rng.uniform(0.005, 0.025)
        amount *= 1.0 - float(skim)
        at += (
            timedelta(days=float(b.rng.uniform(1, 6)))
            if subtle
            else timedelta(minutes=int(b.rng.integers(8, 180)))
        )

    # Loops often hang an external mule off one member
    if not subtle and b.rng.random() < 0.5:
        mule = b.node(age_days=int(b.rng.integers(15, 150)))
        b.edge(ring[0], mule, amount * 0.4, at, suspicious=True)
        b.edge(mule, ring[2 % size], amount * 0.39, at + timedelta(minutes=14), suspicious=True)


def _inject_smurfing(b: _Builder, t0: datetime, subtle: bool = False) -> None:
    """Many small deposits converging on one account, then forwarded onward."""
    collector = b.node(age_days=int(b.rng.integers(200, 1400) if subtle else b.rng.integers(20, 300)))
    count = int(b.rng.integers(8, 20))
    base_amount = float(b.rng.uniform(40_000, 190_000))
    at = t0
    for _ in range(count):
        payer = b.node(age_days=int(b.rng.integers(10, 400)))
        # Blatant: near-identical amounts just under a threshold.
        # Subtle: wide spread and days apart, resembling a real collection account.
        jitter = b.rng.uniform(0.55, 1.45) if subtle else b.rng.uniform(0.96, 1.04)
        amount = base_amount * float(jitter)
        b.edge(payer, collector, amount, at, suspicious=True)
        at += (
            timedelta(hours=float(b.rng.uniform(4, 40)))
            if subtle
            else timedelta(minutes=int(b.rng.integers(1, 25)))
        )
    # Collector forwards the aggregate onward
    onward = b.node(age_days=int(b.rng.integers(20, 300)))
    b.edge(
        collector,
        onward,
        base_amount * count * (0.82 if subtle else 0.98),
        at
        + (
            timedelta(days=float(b.rng.uniform(1, 5)))
            if subtle
            else timedelta(minutes=int(b.rng.integers(3, 40)))
        ),
        suspicious=True,
        international=bool(b.rng.random() < 0.4),
    )


def _inject_fan_out_dispersion(
    b: _Builder, t0: datetime, subtle: bool = False
) -> None:
    """One funded account splits value across many accounts."""
    distributor = b.node(
        age_days=int(b.rng.integers(300, 1600) if subtle else b.rng.integers(15, 200))
    )
    funder = b.node(age_days=int(b.rng.integers(400, 2500)))
    principal = float(b.rng.uniform(1_500_000, 8_000_000))
    b.edge(funder, distributor, principal, t0, suspicious=True)

    count = int(b.rng.integers(7, 18))
    slice_amount = principal / count
    at = t0 + timedelta(minutes=int(b.rng.integers(2, 30)))
    for _ in range(count):
        receiver = b.node(
            age_days=int(b.rng.integers(300, 2000) if subtle else b.rng.integers(5, 120))
        )
        jitter = b.rng.uniform(0.5, 1.5) if subtle else b.rng.uniform(0.94, 1.06)
        amount = slice_amount * float(jitter)
        b.edge(
            distributor,
            receiver,
            amount,
            at,
            suspicious=True,
            international=bool(b.rng.random() < 0.25),
        )
        at += (
            timedelta(hours=float(b.rng.uniform(2, 20)))
            if subtle
            else timedelta(minutes=int(b.rng.integers(1, 12)))
        )


# ---------------------------------------------------------------------------
# Benign topologies (hard negatives)
# ---------------------------------------------------------------------------


def _inject_retail_spoke(b: _Builder, t0: datetime, ambiguous: bool = False) -> None:
    """Ordinary customer paying a handful of merchants over weeks."""
    customer = b.node(age_days=int(b.rng.integers(700, 3600)))
    for _ in range(int(b.rng.integers(4, 12))):
        merchant = b.node(entity_type="MERCHANT", age_days=int(b.rng.integers(900, 3600)))
        for _ in range(int(b.rng.integers(1, 4))):
            b.edge(
                customer,
                merchant,
                float(b.rng.uniform(800, 40_000)),
                t0 + timedelta(hours=float(b.rng.uniform(0, 720))),
                suspicious=False,
            )


def _inject_merchant_collection(
    b: _Builder, t0: datetime, ambiguous: bool = False
) -> None:
    """Legitimate fan-in: a merchant collecting from many customers.

    `ambiguous=True` models a flash sale: near-uniform ticket prices arriving
    minutes apart, then a same-day settlement sweep. Structurally this is close
    to smurfing, and it stays labelled BENIGN - it is the hard negative that
    stops the GNN from equating "fast uniform fan-in" with laundering.
    """
    merchant = b.node(entity_type="MERCHANT", age_days=int(b.rng.integers(1200, 3600)))
    count = int(b.rng.integers(9, 24))
    ticket = float(b.rng.uniform(45_000, 150_000))
    at = t0
    for _ in range(count):
        payer = b.node(age_days=int(b.rng.integers(300, 3600)))
        if ambiguous:
            amount = ticket * float(b.rng.uniform(0.97, 1.03))  # fixed price point
            when = at
            at += timedelta(minutes=int(b.rng.integers(1, 20)))
        else:
            amount = float(b.rng.uniform(500, 85_000))  # wide spread
            when = t0 + timedelta(hours=float(b.rng.uniform(0, 336)))
        b.edge(payer, merchant, amount, when, suspicious=False)

    # Settlement sweep: same-day for the flash-sale variant, weekly otherwise
    settlement = b.node(entity_type="COMPANY", age_days=int(b.rng.integers(1200, 3600)))
    if ambiguous:
        b.edge(
            merchant,
            settlement,
            ticket * count * 0.97,
            at + timedelta(minutes=int(b.rng.integers(5, 90))),
            suspicious=False,
        )
    else:
        for week in range(int(b.rng.integers(1, 4))):
            b.edge(
                merchant,
                settlement,
                float(b.rng.uniform(200_000, 900_000)),
                t0 + timedelta(days=7 * (week + 1)),
                suspicious=False,
            )


def _inject_payroll_fanout(b: _Builder, t0: datetime, ambiguous: bool = False) -> None:
    """Legitimate fan-out: employer paying salaries.

    `ambiguous=True` models a uniform-grade contractor payout run: identical
    amounts to many recently-opened accounts inside one hour. Still BENIGN.
    """
    employer = b.node(entity_type="COMPANY", age_days=int(b.rng.integers(1500, 3600)))
    count = int(b.rng.integers(8, 20))
    flat_rate = float(b.rng.uniform(60_000, 180_000))
    at = t0
    for _ in range(count):
        if ambiguous:
            employee = b.node(age_days=int(b.rng.integers(20, 220)))  # new hires
            b.edge(
                employer,
                employee,
                flat_rate * float(b.rng.uniform(0.99, 1.01)),  # identical grade
                at,
                suspicious=False,
            )
            at += timedelta(minutes=int(b.rng.integers(1, 6)))
        else:
            employee = b.node(age_days=int(b.rng.integers(400, 3600)))
            for month in range(int(b.rng.integers(1, 3))):
                b.edge(
                    employer,
                    employee,
                    float(b.rng.uniform(35_000, 220_000)),  # differing salaries
                    t0 + timedelta(days=30 * month, hours=float(b.rng.uniform(0, 6))),
                    suspicious=False,
                )


def _inject_sme_trade(b: _Builder, t0: datetime, ambiguous: bool = False) -> None:
    """Legitimate business chain: retailer -> distributor -> supplier.

    Normally hops RETAIN a real margin and take days. `ambiguous=True` models a
    same-day back-to-back trade settlement on thin margins - which looks like
    layering but is BENIGN.
    """
    supplier = b.node(entity_type="COMPANY", age_days=int(b.rng.integers(1200, 3600)))
    distributor = b.node(entity_type="COMPANY", age_days=int(b.rng.integers(900, 3600)))
    retailer = b.node(entity_type="MERCHANT", age_days=int(b.rng.integers(700, 3600)))
    for _ in range(int(b.rng.integers(2, 6))):
        amount = float(b.rng.uniform(150_000, 1_200_000))
        at = t0 + timedelta(days=float(b.rng.uniform(0, 60)))
        b.edge(retailer, distributor, amount, at, suspicious=False)
        if ambiguous:
            # Thin margin, forwarded within the hour
            b.edge(
                distributor,
                supplier,
                amount * float(b.rng.uniform(0.94, 0.985)),
                at + timedelta(minutes=int(b.rng.integers(4, 55))),
                suspicious=False,
            )
        else:
            b.edge(
                distributor,
                supplier,
                amount * float(b.rng.uniform(0.55, 0.78)),
                at + timedelta(days=float(b.rng.uniform(2, 14))),
                suspicious=False,
            )


_SUSPICIOUS_INJECTORS = {
    "LAYERED": _inject_layering,
    "CIRCULAR": _inject_circular,
    "SMURFING": _inject_smurfing,
    "FAN_OUT_DISPERSION": _inject_fan_out_dispersion,
}
_BENIGN_INJECTORS = {
    "RETAIL_SPOKE": _inject_retail_spoke,
    "MERCHANT_COLLECTION": _inject_merchant_collection,
    "PAYROLL_FANOUT": _inject_payroll_fanout,
    "SME_TRADE": _inject_sme_trade,
}


def _add_background_noise(b: _Builder, t0: datetime, edge_count: int) -> None:
    """Random low-value chatter so structures are not isolated in empty space."""
    if len(b.nodes) < 4:
        return
    keys = [n.key for n in b.nodes]
    for _ in range(edge_count):
        src, dst = b.rng.choice(len(keys), size=2, replace=False)
        b.edge(
            keys[int(src)],
            keys[int(dst)],
            float(b.rng.uniform(500, 60_000)),
            t0 + timedelta(hours=float(b.rng.uniform(0, 480))),
            suspicious=False,
        )


def generate_labelled_graph(
    rng: np.random.Generator, graph_id: int, force_label: int | None = None
) -> LabelledGraph:
    """Generate one labelled graph.

    Roughly half of graphs contain at least one injected laundering typology;
    every graph also contains benign structures, so the positive class is never
    identifiable from graph size alone.
    """
    b = _Builder(rng, prefix=f"G{graph_id:04d}")
    t0 = BASE_TIME + timedelta(days=int(rng.integers(0, 240)))

    is_positive = (
        bool(force_label) if force_label is not None else bool(rng.random() < 0.5)
    )
    topologies: List[str] = []

    # Always seed 1-3 benign structures, some of them "ambiguous" variants that
    # deliberately mimic laundering signatures. Every NEGATIVE graph is
    # guaranteed at least one mimic, otherwise the graph-level task collapses
    # into "does any node look unusual at all" and scores a meaningless 1.0.
    benign_count = int(rng.integers(1, 4))
    force_mimic_at = int(rng.integers(0, benign_count)) if not is_positive else -1
    for slot in range(benign_count):
        name = str(rng.choice(BENIGN_TOPOLOGIES if slot != force_mimic_at else MIMIC_TOPOLOGIES))
        ambiguous = slot == force_mimic_at or bool(rng.random() < AMBIGUOUS_BENIGN_RATE)
        _BENIGN_INJECTORS[name](
            b, t0 + timedelta(hours=float(rng.uniform(0, 96))), ambiguous
        )
        topologies.append(f"{name}{'*' if ambiguous else ''}")

    if is_positive:
        for _ in range(int(rng.integers(1, 3))):
            name = str(rng.choice(SUSPICIOUS_TOPOLOGIES))
            # A third of positives are the "subtle" variants: slower relays,
            # fatter skims, less uniformity.
            subtle = bool(rng.random() < SUBTLE_SUSPICIOUS_RATE)
            _SUSPICIOUS_INJECTORS[name](
                b, t0 + timedelta(hours=float(rng.uniform(0, 72))), subtle
            )
            topologies.append(f"{name}{'~' if subtle else ''}")

    _add_background_noise(b, t0, int(rng.integers(3, 18)))

    snapshot = build_snapshot(b.nodes, b.edges)
    node_labels = np.array(
        [
            1
            if (key in b.suspicious_nodes and rng.random() >= NODE_LABEL_DROPOUT)
            else 0
            for key in snapshot.node_keys
        ],
        dtype=np.float32,
    )
    edge_labels = np.array(
        [1 if key in b.suspicious_edges else 0 for key in snapshot.edge_keys],
        dtype=np.float32,
    )
    return LabelledGraph(
        snapshot=snapshot,
        node_labels=node_labels,
        edge_labels=edge_labels,
        graph_label=1 if is_positive else 0,
        topologies=topologies,
    )


def generate_dataset(
    n_graphs: int = 700, seed: int = 424242
) -> List[LabelledGraph]:
    rng = np.random.default_rng(seed)
    graphs: List[LabelledGraph] = []
    for i in range(n_graphs):
        # Balance the graph-level label exactly
        force = i % 2
        graph = generate_labelled_graph(rng, graph_id=i, force_label=force)
        if graph.snapshot.num_edges >= 4 and graph.snapshot.num_nodes >= 4:
            graphs.append(graph)
    return graphs


def dataset_summary(graphs: Sequence[LabelledGraph]) -> Dict[str, float]:
    nodes = sum(g.snapshot.num_nodes for g in graphs)
    edges = sum(g.snapshot.num_edges for g in graphs)
    pos_nodes = sum(int(g.node_labels.sum()) for g in graphs)
    pos_edges = sum(int(g.edge_labels.sum()) for g in graphs)
    pos_graphs = sum(g.graph_label for g in graphs)
    return {
        "graphs": len(graphs),
        "nodes": nodes,
        "edges": edges,
        "positive_nodes": pos_nodes,
        "positive_edges": pos_edges,
        "positive_graphs": pos_graphs,
        "node_positive_rate": round(pos_nodes / max(nodes, 1), 4),
        "edge_positive_rate": round(pos_edges / max(edges, 1), 4),
    }
