"""Feature schema v2: the per-account measurements and the vectors built on them."""

from datetime import datetime, timedelta, timezone

import pytest

from app.graph.features_v2 import (
    AMLWORLD_SCHEMA,
    PLATFORM_SCHEMA,
    AccountProfile,
    TransferRecord,
    compute_account_stats,
    edge_feature_vector,
    node_feature_vector,
    payment_rail,
)

EDGE_NAMES = PLATFORM_SCHEMA.edge_feature_names

END = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
START = END - timedelta(days=7)


def t(key, source, target, amount, minutes_before_end, channel="IMPS", intl=False):
    return TransferRecord(
        key=key,
        source=source,
        target=target,
        amount=amount,
        occurred_at=END - timedelta(minutes=minutes_before_end),
        channel=channel,
        is_international=intl,
    )


RELAY = [
    t("T1", "A", "B", 10_000, 120),  # A pays B
    t("T2", "B", "C", 9_800, 115),  # B forwards 98% five minutes later
]


def test_relay_account_measured_as_pass_through():
    b = compute_account_stats("B", RELAY, START, END)
    assert (b.in_count, b.out_count) == (1, 1)
    assert b.pass_through == pytest.approx(0.98)
    assert b.rapid_relay_share == pytest.approx(1.0)
    assert b.median_relay_minutes == pytest.approx(5.0)
    assert b.net_flow == pytest.approx((10_000 - 9_800) / 19_800)


def test_window_is_half_open():
    transfers = [
        t("AT_START", "A", "B", 10, 7 * 24 * 60),  # exactly at window start: excluded
        t("AT_END", "A", "B", 20, 0),  # exactly at window end: included
        t("BEFORE", "A", "B", 30, 7 * 24 * 60 + 1),
    ]
    stats = compute_account_stats("B", transfers, START, END)
    assert stats.in_count == 1
    assert stats.in_value == 20


def test_self_transfers_ignored():
    stats = compute_account_stats("A", [t("S", "A", "A", 500, 10)], START, END)
    assert stats.in_count == stats.out_count == 0


def test_outbound_with_no_earlier_inbound_is_not_a_relay():
    # Funds leave before anything arrives: no relay, whatever the amounts
    transfers = [t("OUT", "B", "C", 100, 60), t("IN", "A", "B", 100, 30)]
    stats = compute_account_stats("B", transfers, START, END)
    assert stats.rapid_relay_share == 0
    assert stats.median_relay_minutes is None


def test_vector_dimensions_match_the_schema():
    a = compute_account_stats("A", RELAY, START, END)
    b = compute_account_stats("B", RELAY, START, END)
    c = compute_account_stats("C", RELAY, START, END)
    for schema in (PLATFORM_SCHEMA, AMLWORLD_SCHEMA):
        node = node_feature_vector(AccountProfile(key="B"), b, True, schema)
        assert len(node) == schema.node_dim == schema.account_dim + 1
        assert node[-1] == 1.0
        assert len(edge_feature_vector(RELAY[0], a, b, schema)) == schema.edge_dim
    # AMLworld has no KYC profiles: those columns are absent, not zero-filled
    assert PLATFORM_SCHEMA.node_dim - AMLWORLD_SCHEMA.node_dim == 9
    assert "pep_flag" not in AMLWORLD_SCHEMA.node_feature_names


def test_edge_time_ordering_and_channel():
    a = compute_account_stats("A", RELAY, START, END)
    b = compute_account_stats("B", RELAY, START, END)
    c = compute_account_stats("C", RELAY, START, END)
    first = dict(zip(EDGE_NAMES, edge_feature_vector(RELAY[0], a, b)))
    second = dict(zip(EDGE_NAMES, edge_feature_vector(RELAY[1], b, c)))

    assert first["has_prior_inbound"] == 0.0  # A never received anything
    assert first["relay_latency_norm"] == 1.0
    assert second["has_prior_inbound"] == 1.0  # B forwards what it received
    assert 0.0 < second["relay_latency_norm"] < 0.5
    assert second["share_of_sender_out"] == pytest.approx(1.0)
    assert first["near_threshold_flag"] == 0.0 and second["near_threshold_flag"] == 1.0

    rail_columns = [k for k in second if k.startswith("rail_")]
    assert sum(second[k] for k in rail_columns) == 1.0
    assert second["rail_instant"] == 1.0  # IMPS
    unknown = edge_feature_vector(t("X", "A", "B", 5, 1, channel="SWIFT"), a, b)
    assert dict(zip(EDGE_NAMES, unknown))["rail_other"] == 1.0


def test_both_datasets_share_payment_rails():
    assert payment_rail("UPI") == payment_rail("IMPS") == "INSTANT"
    assert payment_rail("NEFT") == payment_rail("ACH") == "BATCH"
    assert payment_rail("RTGS") == payment_rail("Wire") == "WIRE"
    assert payment_rail("Credit Card") == payment_rail("CARD") == "CARD"
    assert payment_rail("Bitcoin") == "CRYPTO"
    assert payment_rail(None) == "OTHER"


def test_round_and_threshold_follow_the_original_amount():
    # INR 50,000 is round; its USD value is not - the source's flag wins
    converted = TransferRecord("R", "A", "B", 602.41, END, round_amount=True, near_threshold=False)
    stats = compute_account_stats("B", [converted], START, END)
    assert stats.round_ratio == 1.0
    # Without flags, the schema's reference-currency rule applies (USD 10,000)
    plain = TransferRecord("P", "A", "B", 9_500.0, END - timedelta(minutes=1))
    assert compute_account_stats("B", [plain], START, END).near_threshold_ratio == 1.0
