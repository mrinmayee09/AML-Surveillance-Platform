"""The live path: database source parity with the training path, and the stats store."""

from datetime import date, timedelta

import numpy as np

from app.db.types import utcnow
from app.graph.db_source import DbTransferSource
from app.graph.features_v2 import (
    FEATURE_SCHEMA_VERSION,
    PLATFORM_FX_TO_REFERENCE,
    TransferRecord,
    WindowConfig,
    is_round,
)
from app.graph.window import InMemoryTransferSource, build_window
from app.models import Account, AccountWindowStats, Customer, Transaction
from app.services import account_stats_service

NOW = utcnow().replace(microsecond=0)


def make_world(db):
    """A small ring with a held and a blocked attempt, plus one stale transfer."""
    pep = Customer(customer_ref="CUST-1", name="Pep", onboarded_on=date(2020, 1, 1), pep_flag=True)
    db.add(pep)
    db.flush()
    accounts = {}
    for ref, country in [("A", "India"), ("B", "Panama"), ("C", "India"), ("D", "India")]:
        accounts[ref] = Account(
            account_ref=ref,
            display_name=ref,
            country=country,
            customer_id=pep.id if ref == "A" else None,
            opened_days_ago=30 if ref == "B" else 900,
        )
        db.add(accounts[ref])
    db.flush()

    def txn(ref, source, target, amount, minutes_ago, status="COMPLETED", channel="IMPS"):
        db.add(
            Transaction(
                txn_ref=ref,
                occurred_at=NOW - timedelta(minutes=minutes_ago),
                sender_account_id=accounts[source].id,
                receiver_account_id=accounts[target].id,
                amount=amount,
                channel=channel,
                status=status,
            )
        )

    txn("T1", "A", "B", 900_000, 600)
    txn("T2", "B", "C", 880_000, 590, channel="RTGS")
    txn("T3", "C", "A", 860_000, 580)
    txn("HELD", "A", "D", 50_000, 100, status="HELD")
    txn("BLOCKED", "D", "A", 70_000, 90, status="BLOCKED")
    txn("STALE", "A", "D", 1_000, 60 * 24 * 9)  # nine days ago: outside the window
    db.flush()
    return accounts


def test_db_source_matches_in_memory_reference(db):
    make_world(db)
    live = build_window(DbTransferSource(db), "A", NOW, WindowConfig())

    # Reference: only settled, in-window transfers, converted the documented way
    # (INR -> USD; round / near-threshold judged on the original INR amount)
    rows = db.query(Transaction).filter(Transaction.status == "COMPLETED").all()
    ref_by_id = {a.id: a.account_ref for a in db.query(Account).all()}
    reference = InMemoryTransferSource(
        [
            TransferRecord(
                key=r.txn_ref,
                source=ref_by_id[r.sender_account_id],
                target=ref_by_id[r.receiver_account_id],
                amount=r.amount * PLATFORM_FX_TO_REFERENCE["INR"],
                occurred_at=r.occurred_at,
                channel=r.channel,
                is_international=r.is_international,
                round_amount=is_round(r.amount),
                near_threshold=800_000 <= r.amount <= 999_000,
            )
            for r in rows
        ],
        DbTransferSource(db).profiles(list(ref_by_id.values())).values(),
    )
    expected = build_window(reference, "A", NOW, WindowConfig())

    assert live.node_keys == expected.node_keys == ["A", "B", "C"]
    assert live.edge_keys == expected.edge_keys == ["T1", "T2", "T3"]
    np.testing.assert_array_equal(live.node_features, expected.node_features)
    np.testing.assert_array_equal(live.edge_features, expected.edge_features)
    # Held / blocked attempts never moved money, so D is not reachable
    assert "D" not in live.node_keys


def test_db_profiles_carry_kyc_facts(db):
    make_world(db)
    profiles = DbTransferSource(db).profiles(["A", "B"])
    assert profiles["A"].pep and not profiles["B"].pep
    assert profiles["B"].high_risk_jurisdiction and not profiles["A"].high_risk_jurisdiction
    assert profiles["B"].account_age_days == 30


def test_stats_store_refresh_and_freshness(db):
    accounts = make_world(db)
    written = account_stats_service.refresh(db, window_end=NOW)
    assert written == 3  # A, B, C settled in the window; D only has held/blocked/stale

    row = db.query(AccountWindowStats).filter_by(account_id=accounts["B"].id).one()
    assert row.schema_version == FEATURE_SCHEMA_VERSION
    assert row.stats["in_count"] == 1 and row.stats["out_count"] == 1
    assert len(row.features) > 0

    fresh = account_stats_service.load_fresh(db, ["A", "B", "C"], now=NOW)
    assert set(fresh) == {"A", "B", "C"}

    # A new settled transfer touching C makes C's row stale, and only C's
    db.add(
        Transaction(
            txn_ref="LATE",
            occurred_at=NOW + timedelta(minutes=5),
            sender_account_id=accounts["C"].id,
            receiver_account_id=accounts["D"].id,
            amount=10,
            status="COMPLETED",
        )
    )
    db.flush()
    fresh = account_stats_service.load_fresh(db, ["A", "B", "C"], now=NOW + timedelta(minutes=6))
    assert set(fresh) == {"A", "B"}

    # Too old, or computed under another schema: rejected
    assert account_stats_service.load_fresh(db, ["A"], now=NOW + timedelta(hours=2)) == {}
    row.schema_version = "1.0"
    db.flush()
    assert "B" not in account_stats_service.load_fresh(db, ["B"], now=NOW)


def test_refresh_is_an_upsert(db):
    accounts = make_world(db)
    account_stats_service.refresh(db, ["A"], window_end=NOW)
    account_stats_service.refresh(db, ["A"], window_end=NOW + timedelta(minutes=1))
    rows = db.query(AccountWindowStats).filter_by(account_id=accounts["A"].id).all()
    assert len(rows) == 1
