"""Database seeding + model training.

Run from the `backend` directory:

    python -m seed.seed              # full reset, seed and train both models
    python -m seed.seed --keep       # seed without dropping existing tables
    python -m seed.seed --no-train   # seed only, skip model training
    python -m seed.seed --small      # smaller dataset, faster iteration

After this completes the platform is immediately usable: customers, accounts,
thousands of transactions, laundering structures, risk history, alerts,
investigations, audit entries, a trained RandomForest and a trained GNN.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence

# Allow `python seed/seed.py` as well as `python -m seed.seed`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.base import Base, SessionLocal, engine, init_db  # noqa: E402
from app.models import (  # noqa: E402
    Account,
    Alert,
    AuditLog,
    Counterparty,
    Customer,
    Investigation,
    InvestigationNote,
    Network,
    NetworkEdge,
    NetworkNode,
    Order,
    RiskAssessment,
    Rule,
    Transaction,
    User,
)
from app.models.enums import AssessmentKind, OrderStatus  # noqa: E402
from app.ml.features import FeatureBundle  # noqa: E402
from app.ml.registry import get_proactive_model  # noqa: E402
from app.rules.engine import evaluate, load_rules, sync_rule_catalogue  # noqa: E402
from app.services import (  # noqa: E402
    audit_service,
    feature_service,
    integrity_service,
    investigation_service,
    network_service,
    reactive_service,
    risk_service,
)
from app.services.audit_service import Actor  # noqa: E402
from seed.generators import (  # noqa: E402
    ARCHETYPE_BY_KEY,
    ELEVATED_ARCHETYPES,
    MERCHANTS,
    AccountSpec,
    CustomerSpec,
    Generator,
    OrderSpec,
    TxnSpec,
)

# ---------------------------------------------------------------------------
# Dataset sizing
# ---------------------------------------------------------------------------

PROFILE_FULL = {
    "customers": 120,
    "window_days": 120,
    "beneficiary_pool": 90,
    "layering_rings": 3,
    "circular_rings": 3,
    "smurfing_rings": 2,
    "fan_out_rings": 2,
    "legit_collections": 3,
    "gnn_graphs": 900,
    "gnn_epochs": 26,
    "ml_samples": 18_000,
}
PROFILE_SMALL = {
    "customers": 45,
    "window_days": 75,
    "beneficiary_pool": 40,
    "layering_rings": 2,
    "circular_rings": 2,
    "smurfing_rings": 1,
    "fan_out_rings": 1,
    "legit_collections": 1,
    "gnn_graphs": 200,
    "gnn_epochs": 10,
    "ml_samples": 8_000,
}

DEMO_USERS = [
    {
        "username": "admin",
        "email": "admin@meridian-aml.example.com",
        "full_name": "Priya Raghavan",
        "password": "Admin@2026",
        "role": "ADMIN",
        "team": "Financial Crime Compliance",
    },
    {
        "username": "analyst",
        "email": "analyst@meridian-aml.example.com",
        "full_name": "Arjun Nair",
        "password": "Analyst@2026",
        "role": "ANALYST",
        "team": "AML Operations",
    },
    {
        "username": "analyst2",
        "email": "analyst2@meridian-aml.example.com",
        "full_name": "Sneha Kulkarni",
        "password": "Analyst@2026",
        "role": "ANALYST",
        "team": "AML Operations",
    },
]


def log(message: str) -> None:
    print(f"[seed] {message}", flush=True)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


def reset_database() -> None:
    log("dropping and recreating all tables")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def truncate_data(db: Session) -> None:
    """Clear data rows while leaving the schema in place."""
    log("clearing existing rows")
    for model in (
        NetworkEdge,
        NetworkNode,
        Network,
        InvestigationNote,
        Investigation,
        Alert,
        RiskAssessment,
        Counterparty,
        Transaction,
        Order,
        Account,
        Customer,
        AuditLog,
        Rule,
        User,
    ):
        db.execute(delete(model))
    db.commit()


# ---------------------------------------------------------------------------
# Core seeding
# ---------------------------------------------------------------------------


def seed_users(db: Session) -> Dict[str, User]:
    users: Dict[str, User] = {}
    for spec in DEMO_USERS:
        user = User(
            username=spec["username"],
            email=spec["email"],
            full_name=spec["full_name"],
            password_hash=hash_password(spec["password"]),
            role=spec["role"],
            team=spec["team"],
            is_active=True,
        )
        db.add(user)
        users[spec["username"]] = user
    db.flush()
    log(f"created {len(users)} users (passwords bcrypt-hashed, never stored in plaintext)")
    return users


def _account_row(spec: AccountSpec, customer_id: Optional[int]) -> Account:
    return Account(
        account_ref=spec.ref,
        customer_id=customer_id,
        display_name=spec.display_name,
        entity_type=spec.entity_type,
        institution=spec.institution,
        ifsc=spec.ifsc,
        currency="INR",
        country=spec.country,
        city=spec.city,
        balance=spec.balance,
        is_internal=spec.is_internal,
        is_dormant=spec.is_dormant,
        opened_days_ago=spec.opened_days_ago,
    )


def seed_entities(
    db: Session, gen: Generator, profile: Dict[str, int], now: datetime
) -> Dict[str, object]:
    """Create customers, accounts, merchants, transactions and typologies."""
    window_days = profile["window_days"]

    # --- Merchant accounts ------------------------------------------------
    merchant_specs = [gen.make_merchant_account(name, cat) for name, cat in MERCHANTS]

    # --- Shared beneficiary pool -----------------------------------------
    beneficiary_specs = [
        gen.make_external_account(
            gen.rng.choice(["BENEFICIARY", "BENEFICIARY", "WALLET", "COMPANY"]),
            foreign=gen.rng.random() < 0.12,
        )
        for _ in range(profile["beneficiary_pool"])
    ]

    # --- Customers, guaranteeing coverage of every archetype -------------
    customer_specs: List[CustomerSpec] = []
    guaranteed = [
        "ESCALATING_RISK",
        "ESCALATING_RISK",
        "STRUCTURING",
        "STRUCTURING",
        "MULE_PASS_THROUGH",
        "MULE_PASS_THROUGH",
        "CROSS_BORDER_HIGH_RISK",
        "SME_LEGIT",
        "SME_LEGIT",
        "VOLATILE_LEGIT",
    ]
    for key in guaranteed:
        customer_specs.append(gen.make_customer(now, ARCHETYPE_BY_KEY[key]))
    while len(customer_specs) < profile["customers"]:
        customer_specs.append(gen.make_customer(now))

    # --- Behavioural traffic ---------------------------------------------
    all_txn_specs: List[TxnSpec] = []
    extra_account_specs: List[AccountSpec] = []
    for customer in customer_specs:
        txns, new_accounts = gen.customer_transactions(
            customer=customer,
            merchant_accounts=merchant_specs,
            beneficiary_pool=beneficiary_specs,
            now=now,
            window_days=window_days,
        )
        all_txn_specs.extend(txns)
        extra_account_specs.extend(new_accounts)

    # --- Laundering typologies -------------------------------------------
    typology_accounts: List[AccountSpec] = []
    typology_roles: Dict[str, str] = {}
    structure_log: List[str] = []

    def add_structure(builder, count: int, label: str) -> None:
        for _ in range(count):
            accounts, txns, roles = builder(now)
            typology_accounts.extend(accounts)
            typology_roles.update(roles)
            all_txn_specs.extend(txns)
            structure_log.append(f"{label} ({len(accounts)} accounts, {len(txns)} txns)")

    add_structure(gen.layering_ring, profile["layering_rings"], "layering chain")
    add_structure(gen.circular_ring, profile["circular_rings"], "circular ring")
    add_structure(gen.smurfing_fan_in, profile["smurfing_rings"], "smurfing fan-in")
    add_structure(gen.fan_out_dispersion, profile["fan_out_rings"], "fan-out dispersion")
    add_structure(
        gen.legitimate_merchant_collection,
        profile["legit_collections"],
        "legitimate merchant collection (hard negative)",
    )

    # --- Persist accounts -------------------------------------------------
    account_rows: Dict[str, Account] = {}

    for spec in merchant_specs + beneficiary_specs + extra_account_specs + typology_accounts:
        if spec.ref in account_rows:
            continue
        row = _account_row(spec, None)
        db.add(row)
        account_rows[spec.ref] = row

    customer_rows: Dict[str, Customer] = {}
    for spec in customer_specs:
        customer = Customer(
            customer_ref=spec.ref,
            name=spec.name,
            email=spec.email,
            phone=spec.phone,
            entity_type="CUSTOMER",
            onboarded_on=spec.onboarded_on,
            account_age_years=spec.account_age_years,
            kyc_level=spec.kyc_level,
            pep_flag=spec.pep_flag,
            occupation=spec.occupation,
            city=spec.city,
            country=spec.country,
            risk_country_exposure=spec.risk_country_exposure,
            baseline_avg_amount=spec.baseline_avg_amount,
            baseline_monthly_count=spec.baseline_monthly_count,
            baseline_counterparties=spec.baseline_counterparties,
            seed_archetype=spec.archetype.key,
        )
        db.add(customer)
        db.flush()
        customer_rows[spec.ref] = customer
        for account_spec in spec.accounts:
            row = _account_row(account_spec, customer.id)
            db.add(row)
            account_rows[account_spec.ref] = row

    db.flush()
    log(
        f"created {len(customer_rows)} customers and {len(account_rows)} accounts "
        f"(incl. merchants, wallets, companies and beneficiaries)"
    )
    for entry in structure_log:
        log(f"  structure: {entry}")

    # --- Persist transactions --------------------------------------------
    inserted = 0
    skipped = 0
    for spec in all_txn_specs:
        sender = account_rows.get(spec.sender_ref)
        receiver = account_rows.get(spec.receiver_ref)
        if sender is None or receiver is None or sender.id == receiver.id:
            skipped += 1
            continue
        db.add(
            Transaction(
                txn_ref=spec.ref,
                occurred_at=spec.occurred_at,
                sender_account_id=sender.id,
                receiver_account_id=receiver.id,
                amount=spec.amount,
                currency="INR",
                channel=spec.channel,
                txn_type=spec.txn_type,
                status=spec.status,
                city=spec.city,
                country=spec.country,
                is_international=spec.is_international,
                narrative=spec.narrative,
                # Scores are assigned by the scoring pass below, not invented here
                risk_score=0.0,
                risk_level="LOW",
                scored_by="REACTIVE",
                decision="ALLOW",
                integrity_status="VERIFIED",
            )
        )
        inserted += 1
    db.flush()
    log(f"created {inserted:,} transactions" + (f" ({skipped} invalid skipped)" if skipped else ""))

    return {
        "customers": customer_rows,
        "accounts": account_rows,
        "merchants": merchant_specs,
        "customer_specs": customer_specs,
        "typology_roles": typology_roles,
    }


def seed_counterparties(db: Session) -> int:
    """Materialise the counterparty relationship table from the transactions."""
    log("building counterparty relationships")
    customers: Sequence[Customer] = db.scalars(select(Customer)).all()
    created = 0
    now = datetime.utcnow()

    for customer in customers:
        owned = {a.id for a in customer.accounts}
        if not owned:
            continue
        rows: Sequence[Transaction] = db.scalars(
            select(Transaction).where(
                (Transaction.sender_account_id.in_(owned))
                | (Transaction.receiver_account_id.in_(owned))
            )
        ).all()

        aggregates: Dict[int, Dict[str, object]] = {}
        for txn in rows:
            partner_id = (
                txn.receiver_account_id
                if txn.sender_account_id in owned
                else txn.sender_account_id
            )
            if partner_id in owned:
                continue
            entry = aggregates.setdefault(
                partner_id,
                {
                    "first": txn.occurred_at,
                    "last": txn.occurred_at,
                    "count": 0,
                    "total": 0.0,
                },
            )
            entry["first"] = min(entry["first"], txn.occurred_at)  # type: ignore[assignment]
            entry["last"] = max(entry["last"], txn.occurred_at)  # type: ignore[assignment]
            entry["count"] = int(entry["count"]) + 1  # type: ignore[arg-type]
            entry["total"] = float(entry["total"]) + txn.amount  # type: ignore[arg-type]

        for partner_id, entry in aggregates.items():
            partner = db.get(Account, partner_id)
            if partner is None:
                continue
            first_seen: datetime = entry["first"]  # type: ignore[assignment]
            db.add(
                Counterparty(
                    customer_id=customer.id,
                    account_id=partner_id,
                    display_name=partner.display_name,
                    relationship_type=(
                        "MERCHANT" if partner.entity_type == "MERCHANT" else "BENEFICIARY"
                    ),
                    first_seen_at=first_seen,
                    last_seen_at=entry["last"],  # type: ignore[arg-type]
                    txn_count=int(entry["count"]),  # type: ignore[arg-type]
                    total_amount=round(float(entry["total"]), 2),  # type: ignore[arg-type]
                    is_new=(now - first_seen) <= timedelta(days=30),
                    country=partner.country,
                )
            )
            created += 1

        # Refresh the counterparty baseline now that we know the real figure
        customer.baseline_counterparties = max(len(aggregates) // 2, 1)

    db.flush()
    log(f"created {created:,} counterparty relationships")
    return created


def score_transactions(db: Session) -> int:
    """Score every transaction through the real proactive pipeline.

    This is deliberately not a random assignment: each transaction is scored by
    the same feature extraction + model + rules path the API uses, so the risk
    columns on the dashboard are genuine model output over the seeded behaviour.
    """
    log("scoring transactions through the real risk pipeline (this is the slow part)")
    customers: Sequence[Customer] = db.scalars(select(Customer)).all()
    proactive_rules = load_rules(db, layer="PROACTIVE")
    model = get_proactive_model()
    scored = 0

    for customer in customers:
        owned = {a.id for a in customer.accounts}
        if not owned:
            continue

        # One feature extraction per customer, then per-transaction adjustment.
        # Re-extracting per transaction would be correct but is O(n^2) on a
        # 20k-row seed; the amount-driven signals are recomputed per row below.
        bundle = feature_service.extract_features(db, customer)
        base_metrics = feature_service.rule_metrics(bundle)
        baseline = bundle.context.get("baseline_avg_amount") or 1.0

        rows: Sequence[Transaction] = db.scalars(
            select(Transaction).where(
                (Transaction.sender_account_id.in_(owned))
                | (Transaction.receiver_account_id.in_(owned))
            )
        ).all()

        # Build every per-transaction feature row first, then score the whole
        # batch in ONE model call. Scoring row-by-row costs ~68ms per call in
        # scikit-learn overhead alone, which dominates the entire seed run.
        feature_rows = []
        metric_rows = []
        for txn in rows:
            metrics = dict(base_metrics)
            metrics["amount"] = txn.amount
            metrics["amount_deviation_ratio"] = txn.amount / float(baseline)
            features = dict(bundle.values)
            features["amount_deviation_ratio"] = metrics["amount_deviation_ratio"]
            features["amount_log"] = math.log1p(txn.amount)
            feature_rows.append(features)
            metric_rows.append(metrics)

        probabilities = model.predict_proba_batch(feature_rows)

        for txn, features, metrics, probability in zip(
            rows, feature_rows, metric_rows, probabilities
        ):
            hits = evaluate(proactive_rules, metrics)
            # explain=False: bulk scoring only needs the score, not the 19-call
            # per-feature attribution. Factor breakdowns are computed on demand
            # by the API when an investigator opens a transaction.
            result = risk_service.score(
                FeatureBundle(values=features, context=bundle.context),
                hits,
                explain=False,
                probability=float(probability),
            )
            txn.risk_score = result.score
            txn.risk_level = result.level
            txn.decision = result.decision
            txn.scored_by = "REACTIVE"
            txn.triggered_rules = ",".join(result.triggered_rule_codes)
            scored += 1

        # Persist the customer-level assessment history (the trajectory chart)
        seed_risk_history(db, customer, bundle, proactive_rules)

    db.flush()
    log(f"scored {scored:,} transactions")
    return scored


def seed_risk_history(
    db: Session, customer: Customer, bundle, proactive_rules
) -> None:
    """Write 8 weekly proactive assessments so trajectories are real history."""
    archetype = ARCHETYPE_BY_KEY.get(customer.seed_archetype)
    escalating = bool(archetype and archetype.escalates)
    now = datetime.utcnow()

    for week in range(8):
        # Oldest first; scale the amount signal to reproduce the trajectory
        progress = week / 7.0
        if escalating:
            factor = 0.18 + progress * 0.92
        elif customer.seed_archetype in ELEVATED_ARCHETYPES:
            factor = 0.75 + progress * 0.3
        else:
            factor = 0.9 + (progress * 0.12)

        values = dict(bundle.values)
        for key in (
            "amount_deviation_ratio",
            "frequency_ratio",
            "counterparty_growth_ratio",
            "new_counterparties_30d",
            "velocity_per_hour",
            "rapid_movement_score",
        ):
            values[key] = float(values.get(key, 0.0)) * factor

        scaled = FeatureBundle(values=values, context=bundle.context)
        metrics = feature_service.rule_metrics(scaled)
        hits = evaluate(proactive_rules, metrics)
        # Only the newest assessment carries a full factor breakdown - that is
        # the one the customer profile and watchlist read.
        result = risk_service.score(scaled, hits, explain=(week == 7))

        assessed_at = now - timedelta(weeks=(7 - week))
        trend = "STABLE"
        if week > 0:
            trend = "INCREASING" if factor > 0.6 and escalating else "STABLE"

        result.trend = trend
        risk_service.persist_assessment(
            db=db,
            result=result,
            kind=AssessmentKind.PROACTIVE.value,
            customer=customer,
            assessed_at=assessed_at,
            notes=f"Weekly proactive assessment (week {week + 1} of 8).",
        )


def seed_orders(
    db: Session, gen: Generator, context: Dict[str, object], now: datetime
) -> int:
    """Create orders for the integrity gateway, each with a signed digest."""
    customer_rows: Dict[str, Customer] = context["customers"]  # type: ignore[assignment]
    account_rows: Dict[str, Account] = context["accounts"]  # type: ignore[assignment]
    merchant_specs: List[AccountSpec] = context["merchants"]  # type: ignore[assignment]
    customer_specs: List[CustomerSpec] = context["customer_specs"]  # type: ignore[assignment]

    created = 0
    for spec in customer_specs:
        customer = customer_rows[spec.ref]
        # Two payable orders each, plus occasional paid history
        for index in range(2):
            merchant_spec = gen.rng.choice(merchant_specs)
            merchant_account = account_rows[merchant_spec.ref]
            order_spec = gen.make_order(spec, merchant_spec, now)
            order = Order(
                order_ref=order_spec.ref,
                customer_id=customer.id,
                merchant_name=order_spec.merchant_name,
                merchant_account_id=merchant_account.id,
                description=order_spec.description,
                authorized_amount=order_spec.authorized_amount,
                currency=order_spec.currency,
                status=OrderStatus.AWAITING_PAYMENT.value,
                created_at=order_spec.created_at,
            )
            integrity_service.sign_order(order, customer.customer_ref)
            db.add(order)
            created += 1

    # One canonical INR 8,000 order matching the specification example, so the
    # gateway page always has the documented scenario available.
    showcase_customer = customer_rows[customer_specs[0].ref]
    showcase_merchant = account_rows[merchant_specs[0].ref]
    showcase = Order(
        order_ref="ORD-82341",
        customer_id=showcase_customer.id,
        merchant_name=showcase_merchant.display_name,
        merchant_account_id=showcase_merchant.id,
        description="Electronics order - reference integrity scenario",
        authorized_amount=8_000.00,
        currency="INR",
        status=OrderStatus.AWAITING_PAYMENT.value,
        created_at=now - timedelta(hours=3),
    )
    integrity_service.sign_order(showcase, showcase_customer.customer_ref)
    db.add(showcase)
    created += 1

    db.flush()
    log(f"created {created} orders (each signed with an HMAC integrity digest)")
    log(f"  reference scenario: ORD-82341 authorised at INR 8,000.00")
    return created


def seed_detection(db: Session, users: Dict[str, User]) -> Dict[str, int]:
    """Run the reactive sweep, graph/GNN analysis and raise real alerts."""
    log("running reactive monitoring sweep")
    reactive_alerts = reactive_service.run_monitoring_sweep(db, create_alerts=True)
    db.flush()
    log(f"  reactive layer raised {len(reactive_alerts)} alert(s)")

    log("building the transaction graph and running GNN inference")
    started = time.perf_counter()
    networks = network_service.analyse_graph(db, persist=True)
    db.flush()
    elapsed = time.perf_counter() - started
    suspicious = [n for n in networks if n.is_suspicious]
    log(
        f"  detected {len(networks)} cluster(s), {len(suspicious)} flagged suspicious "
        f"in {elapsed:.1f}s"
    )
    for network in sorted(suspicious, key=lambda n: n.risk_score, reverse=True)[:6]:
        log(
            f"    {network.network_ref} {network.pattern:<9} risk={network.risk_score:>5} "
            f"nodes={network.node_count:>3} edges={network.edge_count:>3} "
            f"flow={network.total_flow:,.0f}"
        )

    network_alerts = network_service.raise_network_alerts(db, networks)
    db.flush()
    log(f"  network layer raised {len(network_alerts)} alert(s)")

    # Assign a share of alerts and open investigations on the most severe
    analyst = users["analyst"]
    analyst2 = users["analyst2"]
    admin = users["admin"]
    actor = Actor.system("seed-pipeline")

    all_alerts: Sequence[Alert] = db.scalars(
        select(Alert).order_by(Alert.risk_score.desc())
    ).all()

    for index, alert in enumerate(all_alerts):
        if index % 3 == 0:
            alert.assignee_id = analyst.id
            if alert.status == "NEW":
                alert.status = "UNDER_REVIEW"
        elif index % 5 == 0:
            alert.assignee_id = analyst2.id

    cases = 0
    for alert in all_alerts[:10]:
        investigation = investigation_service.create_investigation(
            db=db,
            title=f"Review of {alert.alert_type} - {alert.alert_ref}",
            actor=actor,
            author=analyst if cases % 2 == 0 else analyst2,
            alert=alert,
            customer=alert.customer,
            network=alert.network,
            priority="HIGH" if alert.risk_score >= 70 else "MEDIUM",
            summary=(
                "Case opened by the seeding pipeline to give the workspace realistic "
                "history. Aggregates the alert, its explanation and any linked network."
            ),
            assignee=analyst if cases % 2 == 0 else analyst2,
            opened_at=alert.raised_at + timedelta(hours=2),
        )
        db.flush()

        # A couple of cases carry a richer note history
        if cases < 4:
            investigation_service.record_note(
                db=db,
                investigation=investigation,
                body=(
                    "Requested source-of-funds documentation and counterparty "
                    "verification. Model output is being treated as a prioritisation "
                    "signal only; no conclusion has been reached."
                ),
                author=analyst,
                actor=actor,
            )
        if cases == 0:
            investigation_service.transition(
                db=db,
                investigation=investigation,
                new_status="IN_PROGRESS",
                actor=actor,
                author=analyst,
                note="Documentation request issued to the relationship manager.",
            )
        cases += 1

    db.flush()
    log(f"  opened {cases} investigations with notes and status history")

    # Seed a handful of representative audit entries
    audit_service.record(
        db,
        Actor.from_user(admin, ip_address="10.20.4.11", session_id="seed-session"),
        action="SYSTEM_SEEDED",
        resource_type="SYSTEM",
        resource_ref="DATABASE",
        new_state="SEEDED",
        detail=(
            "Demo dataset generated: customers, accounts, transactions, laundering "
            "structures, risk history, alerts and investigations."
        ),
    )
    db.commit()

    return {
        "reactive_alerts": len(reactive_alerts),
        "network_alerts": len(network_alerts),
        "networks": len(networks),
        "suspicious": len(suspicious),
        "investigations": cases,
    }


# ---------------------------------------------------------------------------
# Model training
# ---------------------------------------------------------------------------


def train_models(profile: Dict[str, int]) -> None:
    log("training the proactive RandomForest model")
    from app.ml.registry import reload_proactive_model
    from app.ml.trainer import train_and_save

    train_and_save(settings.ml_model_abspath, n_samples=profile["ml_samples"])
    reload_proactive_model()

    log("training the graph neural network")
    try:
        from app.gnn.registry import reload_gnn_engine
        from app.gnn.trainer import train_and_save as train_gnn

        train_gnn(
            settings.gnn_model_abspath,
            n_graphs=profile["gnn_graphs"],
            epochs=profile["gnn_epochs"],
        )
        reload_gnn_engine()
    except RuntimeError as exc:
        log(f"  GNN training skipped: {exc}")
        log("  the platform will use the analytic engine and report it as UNTRAINED")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def seed_database(
    reset: bool = True, train: bool = True, small: bool = False, seed_value: int = 20260818
) -> Dict[str, object]:
    profile = PROFILE_SMALL if small else PROFILE_FULL
    started = time.perf_counter()

    log(f"database: {settings.database_url}")
    log(f"profile: {'small' if small else 'full'}")

    if reset:
        reset_database()
    else:
        init_db()

    # Models are trained BEFORE scoring, so the seeded risk columns come from
    # the trained model rather than the untrained fallback.
    if train:
        train_models(profile)

    db = SessionLocal()
    try:
        if not reset:
            truncate_data(db)

        users = seed_users(db)
        created = sync_rule_catalogue(db)
        db.flush()
        log(f"seeded {created} AML rules into the rules engine")

        gen = Generator(seed=seed_value)
        now = datetime.utcnow()

        context = seed_entities(db, gen, profile, now)
        db.commit()

        seed_counterparties(db)
        db.commit()

        seed_orders(db, gen, context, now)
        db.commit()

        score_transactions(db)
        db.commit()

        stats = seed_detection(db, users)

        # --- Final summary -------------------------------------------------
        counts = {
            "users": db.scalar(select(func.count(User.id))),
            "customers": db.scalar(select(func.count(Customer.id))),
            "accounts": db.scalar(select(func.count(Account.id))),
            "orders": db.scalar(select(func.count(Order.id))),
            "transactions": db.scalar(
                select(func.count(Transaction.id))
            ),
            "counterparties": db.scalar(
                select(func.count(Counterparty.id))
            ),
            "risk_assessments": db.scalar(
                select(func.count(RiskAssessment.id))
            ),
            "alerts": db.scalar(select(func.count(Alert.id))),
            "networks": db.scalar(select(func.count(Network.id))),
            "investigations": db.scalar(
                select(func.count(Investigation.id))
            ),
            "audit_logs": db.scalar(select(func.count(AuditLog.id))),
            "rules": db.scalar(select(func.count(Rule.id))),
        }
        db.commit()
    finally:
        db.close()

    elapsed = time.perf_counter() - started
    print()
    log("=" * 66)
    log(f"SEEDING COMPLETE in {elapsed:.1f}s")
    log("=" * 66)
    for key, value in counts.items():
        log(f"  {key:<18} {value:,}")
    log(f"  suspicious networks {stats['suspicious']}")
    print()
    log("Demo credentials:")
    for spec in DEMO_USERS:
        log(f"  {spec['role']:<8} {spec['username']:<9} / {spec['password']}")
    print()
    log("Reference integrity scenario: order ORD-82341, authorised INR 8,000.00")
    log("  Submit INR 8,000  -> VERIFIED")
    log("  Submit INR 80,000 -> TRANSACTION INTEGRITY FAILURE, payment BLOCKED")
    print()

    return {"counts": counts, "detection": stats}


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the AML platform database.")
    parser.add_argument(
        "--keep", action="store_true", help="do not drop tables, just clear rows"
    )
    parser.add_argument("--no-train", action="store_true", help="skip model training")
    parser.add_argument(
        "--small", action="store_true", help="smaller dataset for faster iteration"
    )
    parser.add_argument("--seed", type=int, default=20260818, help="RNG seed")
    args = parser.parse_args()

    seed_database(
        reset=not args.keep,
        train=not args.no_train,
        small=args.small,
        seed_value=args.seed,
    )


if __name__ == "__main__":
    main()
