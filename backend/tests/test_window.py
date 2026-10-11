"""Neighbourhood windows built over in-memory sources (the training path)."""

from datetime import datetime, timedelta, timezone

import numpy as np

from app.db.types import as_utc
from app.graph.features_v2 import PLATFORM_SCHEMA, TransferRecord, WindowConfig
from app.graph.synthetic import generate_dataset
from app.graph.window import InMemoryTransferSource, build_window

END = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def t(key, source, target, amount, minutes_before_end):
    return TransferRecord(
        key=key,
        source=source,
        target=target,
        amount=amount,
        occurred_at=END - timedelta(minutes=minutes_before_end),
    )


def chain_source():
    # A -> B -> C -> D, plus D paying an account E that is 4 hops from A
    return InMemoryTransferSource(
        [
            t("T1", "A", "B", 500_000, 300),
            t("T2", "B", "C", 490_000, 290),
            t("T3", "C", "D", 480_000, 280),
            t("T4", "D", "E", 470_000, 270),
            t("OLD", "A", "B", 1, 8 * 24 * 60),  # outside the 7-day window
        ]
    )


def test_hops_seed_first_and_ego_marker():
    window = build_window(chain_source(), "A", END, WindowConfig(hops=2))
    assert window.node_keys == ["A", "B", "C"]
    assert window.node_hops == {"A": 0, "B": 1, "C": 2}
    assert window.node_features[:, -1].tolist() == [1.0, 0.0, 0.0]
    assert window.edge_keys == ["T1", "T2"]  # OLD is outside the window
    assert window.edge_index.tolist() == [[0, 1], [1, 2]]


def test_features_are_institution_wide_not_window_local():
    # C is the edge of A's 2-hop window, but its stats still count C -> D
    window = build_window(chain_source(), "A", END, WindowConfig(hops=2))
    c = window.stats["C"]
    assert (c.in_count, c.out_count) == (1, 1)
    assert "T3" not in window.edge_keys


def test_account_features_identical_in_every_view():
    graph = generate_dataset(n_graphs=4, seed=7)[1]
    source = InMemoryTransferSource.from_graph_records(
        list(graph.snapshot.nodes.values()), graph.snapshot.edges
    )
    end = as_utc(max(e.occurred_at for e in graph.snapshot.edges))

    config = WindowConfig(days=30)
    windows = [build_window(source, seed, end, config) for seed in source.account_keys[:12]]
    seen = {}
    for window in windows:
        for i, key in enumerate(window.node_keys):
            row = window.node_features[i, : PLATFORM_SCHEMA.account_dim]
            if key in seen:
                np.testing.assert_array_equal(seen[key], row, err_msg=f"{key} differs between views")
            else:
                seen[key] = row
    shared = sum(1 for w in windows for k in w.node_keys) - len(seen)
    assert shared > 0, "test needs at least one account seen from two seeds"


def test_hub_is_included_but_not_expanded():
    transfers = [t("IN", "A", "HUB", 1_000, 100)]
    transfers += [t(f"P{i}", f"C{i:02d}", "HUB", 100, 50) for i in range(60)]
    window = build_window(InMemoryTransferSource(transfers), "A", END, WindowConfig(hops=2))
    assert window.node_keys == ["A", "HUB"]
    assert window.hubs_not_expanded == ["HUB"]
    assert window.stats["HUB"].partners_in == 61  # its stats still see everyone


def test_node_cap_keeps_strongest_links_deterministically():
    transfers = [t(f"T{i}", "A", f"B{i:02d}", 1_000 + i, 100) for i in range(20)]
    source = InMemoryTransferSource(transfers)
    config = WindowConfig(hops=1, max_nodes=6, hub_partner_limit=100)
    first = build_window(source, "A", END, config)
    again = build_window(source, "A", END, config)

    assert first.truncated_nodes
    assert first.node_keys == ["A", "B15", "B16", "B17", "B18", "B19"]
    assert first.node_keys == again.node_keys
    np.testing.assert_array_equal(first.node_features, again.node_features)
    np.testing.assert_array_equal(first.edge_features, again.edge_features)


def test_edge_cap_keeps_largest_transfers():
    transfers = [t(f"T{i:02d}", "A", "B", 100 + i, 100 - i) for i in range(10)]
    window = build_window(InMemoryTransferSource(transfers), "A", END, WindowConfig(max_edges=3))
    assert window.truncated_edges
    assert sorted(window.edge_keys) == ["T07", "T08", "T09"]
    # Still in time order, so time-ordered aggregation can rely on it
    minutes = window.edge_minutes_before_end.tolist()
    assert minutes == sorted(minutes, reverse=True)
