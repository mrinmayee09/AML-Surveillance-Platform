"""Realistic AML mock-data generators.

Design goals:

  * Behaviour, not noise. Every customer follows a documented archetype with its
    own amount distribution, cadence and counterparty profile, so the
    behavioural features the model reads are genuinely informative.
  * Recognisable typologies. Laundering structures are constructed explicitly
    (layering chain, circular ring, smurfing fan-in, fan-out dispersion) so the
    graph engine has real patterns to find rather than random edges.
  * Hard negatives. Legitimate high-volume businesses and volatile-but-honest
    customers exist too, so a detector cannot succeed by flagging size alone.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

FIRST_NAMES = [
    "Rahul", "Priya", "Amit", "Sneha", "Vikram", "Ananya", "Rohan", "Kavya",
    "Arjun", "Meera", "Karan", "Divya", "Suresh", "Nisha", "Aditya", "Pooja",
    "Manish", "Ritu", "Sanjay", "Deepika", "Nikhil", "Shreya", "Varun", "Anjali",
    "Rajesh", "Swati", "Harsh", "Neha", "Gaurav", "Lakshmi", "Aman", "Ishita",
    "Farhan", "Zoya", "Imran", "Ayesha", "Tarun", "Bhavna", "Naveen", "Sana",
]
LAST_NAMES = [
    "Sharma", "Verma", "Patel", "Reddy", "Iyer", "Nair", "Singh", "Gupta",
    "Mehta", "Joshi", "Desai", "Kulkarni", "Chatterjee", "Banerjee", "Rao",
    "Malhotra", "Kapoor", "Bose", "Menon", "Pillai", "Khan", "Ahmed", "Shetty",
    "Bhat", "Chauhan", "Trivedi", "Mishra", "Saxena", "Ghosh", "Pandey",
]
CITIES: List[Tuple[str, str]] = [
    ("Mumbai", "India"), ("Delhi", "India"), ("Bengaluru", "India"),
    ("Chennai", "India"), ("Hyderabad", "India"), ("Pune", "India"),
    ("Kolkata", "India"), ("Ahmedabad", "India"), ("Jaipur", "India"),
    ("Kochi", "India"), ("Gurugram", "India"), ("Noida", "India"),
]
FOREIGN_CITIES: List[Tuple[str, str]] = [
    ("Singapore", "Singapore"), ("Dubai", "United Arab Emirates"),
    ("London", "United Kingdom"), ("Hong Kong", "Hong Kong"),
    ("Nicosia", "Cyprus"), ("Panama City", "Panama"),
    ("Victoria", "Seychelles"), ("George Town", "Cayman Islands"),
]
HIGH_RISK_FOREIGN = {"Cyprus", "Panama", "Seychelles", "Cayman Islands"}

OCCUPATIONS = [
    "Software engineer", "Teacher", "Doctor", "Retail owner", "Consultant",
    "Accountant", "Logistics manager", "Textile trader", "Jeweller",
    "Real-estate agent", "Restaurateur", "Freelance designer", "Civil servant",
    "Pharmacist", "Construction contractor", "Import/export trader",
]
MERCHANTS = [
    ("Kirana Direct", "Groceries"), ("StyleCart", "Apparel"),
    ("TechNova Retail", "Electronics"), ("MediPlus Pharmacy", "Pharmacy"),
    ("UrbanFuel", "Fuel"), ("Wanderly Travel", "Travel"),
    ("HomeNest Furnishings", "Home"), ("FitLane Sports", "Sports"),
    ("BookBay", "Books"), ("Cafe Meridian", "Food & beverage"),
    ("GoldLeaf Jewellers", "Jewellery"), ("BuildRight Materials", "Construction"),
]
CHANNELS = ["UPI", "NEFT", "IMPS", "RTGS", "CARD", "WALLET"]
CHANNEL_WEIGHTS = [0.44, 0.14, 0.16, 0.06, 0.15, 0.05]

INSTITUTIONS = [
    "Meridian Bank", "Coastal National", "Deccan Union Bank",
    "Himalaya Trust Bank", "Peninsula Financial",
]

# ---------------------------------------------------------------------------
# Customer archetypes
# ---------------------------------------------------------------------------


@dataclass
class Archetype:
    """A behavioural profile the generator samples transactions from."""

    key: str
    label: str
    description: str
    # Log-normal parameters for transaction amounts (INR)
    amount_median: float
    amount_sigma: float
    # Transactions per month
    monthly_count: Tuple[int, int]
    counterparties: Tuple[int, int]
    account_age_years: Tuple[float, float]
    international_rate: float
    high_risk_geo_rate: float
    # Whether the archetype ESCALATES over the observation window - the thing
    # the proactive layer is meant to catch before it becomes a network case.
    escalates: bool = False
    pep_rate: float = 0.02
    # Multiplier applied to amounts in the final weeks when escalating
    escalation_factor: float = 1.0
    weight: float = 1.0


ARCHETYPES: List[Archetype] = [
    Archetype(
        key="RETAIL_STABLE",
        label="Stable retail customer",
        description="INR 5K-25K payments, consistent cadence, few counterparties.",
        amount_median=12_000,
        amount_sigma=0.55,
        monthly_count=(8, 26),
        counterparties=(3, 8),
        account_age_years=(2.5, 11.0),
        international_rate=0.01,
        high_risk_geo_rate=0.0,
        weight=0.34,
    ),
    Archetype(
        key="SALARIED_LOW",
        label="Salaried, low activity",
        description="Regular salary credits, a handful of recurring payments.",
        amount_median=22_000,
        amount_sigma=0.45,
        monthly_count=(4, 12),
        counterparties=(2, 6),
        account_age_years=(3.0, 14.0),
        international_rate=0.005,
        high_risk_geo_rate=0.0,
        weight=0.18,
    ),
    Archetype(
        key="SME_LEGIT",
        label="Legitimate SME (hard negative)",
        description=(
            "High volume, high value, genuinely cross-border. Deliberately looks "
            "risky on size alone so detectors cannot use amount as a shortcut."
        ),
        amount_median=180_000,
        amount_sigma=0.85,
        monthly_count=(45, 110),
        counterparties=(18, 45),
        account_age_years=(4.0, 15.0),
        international_rate=0.26,
        high_risk_geo_rate=0.02,
        pep_rate=0.04,
        weight=0.14,
    ),
    Archetype(
        key="VOLATILE_LEGIT",
        label="Volatile but legitimate (hard negative)",
        description="Erratic amounts and cadence with a benign explanation.",
        amount_median=55_000,
        amount_sigma=1.15,
        monthly_count=(10, 40),
        counterparties=(6, 18),
        account_age_years=(1.0, 6.0),
        international_rate=0.07,
        high_risk_geo_rate=0.01,
        weight=0.12,
    ),
    Archetype(
        key="ESCALATING_RISK",
        label="Escalating behaviour",
        description=(
            "Starts ordinary, then amounts and counterparties climb sharply - the "
            "trajectory the proactive layer exists to surface early."
        ),
        amount_median=28_000,
        amount_sigma=0.7,
        monthly_count=(12, 35),
        counterparties=(5, 14),
        account_age_years=(0.8, 3.5),
        international_rate=0.08,
        high_risk_geo_rate=0.06,
        escalates=True,
        escalation_factor=9.0,
        weight=0.09,
    ),
    Archetype(
        key="STRUCTURING",
        label="Threshold-adjacent structuring",
        description="Repeated amounts just under the INR 10L reporting threshold.",
        amount_median=880_000,
        amount_sigma=0.10,
        monthly_count=(30, 70),
        counterparties=(8, 20),
        account_age_years=(0.5, 3.0),
        international_rate=0.06,
        high_risk_geo_rate=0.05,
        weight=0.05,
    ),
    Archetype(
        key="MULE_PASS_THROUGH",
        label="Pass-through / mule behaviour",
        description="Receives large sums and forwards almost all of it in minutes.",
        amount_median=650_000,
        amount_sigma=0.9,
        monthly_count=(20, 55),
        counterparties=(10, 28),
        account_age_years=(0.2, 1.6),
        international_rate=0.18,
        high_risk_geo_rate=0.14,
        weight=0.05,
    ),
    Archetype(
        key="CROSS_BORDER_HIGH_RISK",
        label="Cross-border, elevated-risk corridors",
        description="Majority of value routed through elevated-risk jurisdictions.",
        amount_median=1_200_000,
        amount_sigma=0.8,
        monthly_count=(12, 32),
        counterparties=(8, 22),
        account_age_years=(1.0, 4.5),
        international_rate=0.68,
        high_risk_geo_rate=0.55,
        pep_rate=0.18,
        weight=0.03,
    ),
]

ARCHETYPE_BY_KEY = {a.key: a for a in ARCHETYPES}
# Archetypes whose behaviour the reactive/network layers are expected to flag
ELEVATED_ARCHETYPES = {
    "ESCALATING_RISK",
    "STRUCTURING",
    "MULE_PASS_THROUGH",
    "CROSS_BORDER_HIGH_RISK",
}


# ---------------------------------------------------------------------------
# Plain data records the seeder converts into ORM rows
# ---------------------------------------------------------------------------


@dataclass
class CustomerSpec:
    ref: str
    name: str
    email: str
    phone: str
    archetype: Archetype
    onboarded_on: date
    account_age_years: float
    city: str
    country: str
    occupation: str
    pep_flag: bool
    kyc_level: str
    baseline_avg_amount: float
    baseline_monthly_count: float
    baseline_counterparties: int
    risk_country_exposure: float
    accounts: List["AccountSpec"] = field(default_factory=list)


@dataclass
class AccountSpec:
    ref: str
    display_name: str
    entity_type: str
    institution: str
    ifsc: str
    city: str
    country: str
    balance: float
    opened_days_ago: int
    is_dormant: bool
    customer_ref: Optional[str] = None
    is_internal: bool = True


@dataclass
class TxnSpec:
    ref: str
    occurred_at: datetime
    sender_ref: str
    receiver_ref: str
    amount: float
    channel: str
    txn_type: str
    city: str
    country: str
    is_international: bool
    narrative: str
    status: str = "COMPLETED"
    # Tags the seeder uses to attribute a transaction to a typology
    typology: Optional[str] = None


@dataclass
class OrderSpec:
    ref: str
    customer_ref: str
    merchant_name: str
    merchant_account_ref: str
    description: str
    authorized_amount: float
    currency: str
    status: str
    created_at: datetime


class Generator:
    """Deterministic generator - same seed produces the same dataset."""

    def __init__(self, seed: int = 20260818):
        self.rng = random.Random(seed)
        self._customer_n = 0
        self._account_n = 0
        self._txn_n = 0
        self._order_n = 0
        self.used_names: set[str] = set()

    # --- id helpers -------------------------------------------------------

    def customer_ref(self) -> str:
        self._customer_n += 1
        return f"CUST-{1000 + self._customer_n}"

    def account_ref(self) -> str:
        self._account_n += 1
        return f"ACCT-{700000 + self._account_n * 7}"

    def txn_ref(self) -> str:
        self._txn_n += 1
        return f"TXN-{self._txn_n:07d}"

    def order_ref(self) -> str:
        self._order_n += 1
        return f"ORD-{82000 + self._order_n}"

    # --- primitives -------------------------------------------------------

    def person_name(self) -> str:
        for _ in range(200):
            name = f"{self.rng.choice(FIRST_NAMES)} {self.rng.choice(LAST_NAMES)}"
            if name not in self.used_names:
                self.used_names.add(name)
                return name
        return f"{self.rng.choice(FIRST_NAMES)} {self.rng.choice(LAST_NAMES)}"

    def lognormal_amount(self, median: float, sigma: float) -> float:
        """Log-normal draw, rounded the way real payment amounts look."""
        value = self.rng.lognormvariate(math.log(median), sigma)
        value = max(value, 100.0)
        if value < 10_000:
            return round(value, -1)
        if value < 1_00_000:
            return round(value, -2)
        return round(value, -2)

    def pick_channel(self, amount: float) -> str:
        """Channel choice respects real rail limits (UPI caps around INR 1L)."""
        if amount >= 2_00_000:
            return self.rng.choices(["RTGS", "NEFT", "SWIFT"], [0.5, 0.4, 0.1])[0]
        if amount >= 1_00_000:
            return self.rng.choices(["NEFT", "IMPS", "RTGS"], [0.5, 0.35, 0.15])[0]
        return self.rng.choices(CHANNELS, CHANNEL_WEIGHTS)[0]

    def business_time(self, day: datetime, night_bias: float = 0.08) -> datetime:
        """A plausible timestamp within a day, mostly during waking hours."""
        if self.rng.random() < night_bias:
            hour = self.rng.choice([0, 1, 2, 3, 4, 23])
        else:
            hour = int(min(max(self.rng.gauss(14, 3.6), 7), 22))
        return day.replace(
            hour=hour,
            minute=self.rng.randrange(60),
            second=self.rng.randrange(60),
            microsecond=0,
        )

    # --- customers --------------------------------------------------------

    def pick_archetype(self) -> Archetype:
        weights = [a.weight for a in ARCHETYPES]
        return self.rng.choices(ARCHETYPES, weights)[0]

    def make_customer(self, now: datetime, archetype: Optional[Archetype] = None) -> CustomerSpec:
        arch = archetype or self.pick_archetype()
        age_years = round(self.rng.uniform(*arch.account_age_years), 2)
        onboarded = (now - timedelta(days=int(age_years * 365))).date()
        city, country = self.rng.choice(CITIES)
        name = self.person_name()
        ref = self.customer_ref()

        baseline_avg = self.lognormal_amount(arch.amount_median, arch.amount_sigma * 0.4)
        baseline_count = float(self.rng.randint(*arch.monthly_count))
        baseline_cp = self.rng.randint(*arch.counterparties)

        customer = CustomerSpec(
            ref=ref,
            name=name,
            email=f"{name.split()[0].lower()}.{name.split()[1].lower()}@example.com",
            phone=f"+91-{self.rng.randrange(70000, 99999)}{self.rng.randrange(10000, 99999)}",
            archetype=arch,
            onboarded_on=onboarded,
            account_age_years=age_years,
            city=city,
            country=country,
            occupation=self.rng.choice(OCCUPATIONS),
            pep_flag=self.rng.random() < arch.pep_rate,
            kyc_level=self.rng.choices(["FULL", "FULL", "FULL", "SIMPLIFIED"])[0],
            baseline_avg_amount=baseline_avg,
            baseline_monthly_count=baseline_count,
            baseline_counterparties=baseline_cp,
            risk_country_exposure=round(arch.high_risk_geo_rate, 3),
        )

        # One primary account, occasionally a second
        account_count = 2 if self.rng.random() < 0.22 else 1
        for index in range(account_count):
            customer.accounts.append(
                AccountSpec(
                    ref=self.account_ref(),
                    display_name=f"{name} - {'Savings' if index == 0 else 'Current'}",
                    entity_type="ACCOUNT",
                    institution=self.rng.choice(INSTITUTIONS),
                    ifsc=f"MRDN0{self.rng.randrange(100000, 999999)}",
                    city=city,
                    country=country,
                    balance=round(
                        max(baseline_avg * self.rng.uniform(1.5, 22.0), 2_500), -2
                    ),
                    opened_days_ago=int(age_years * 365),
                    is_dormant=self.rng.random() < 0.05,
                    customer_ref=ref,
                )
            )
        return customer

    def make_merchant_account(self, merchant: str, category: str) -> AccountSpec:
        city, country = self.rng.choice(CITIES)
        return AccountSpec(
            ref=self.account_ref(),
            display_name=f"{merchant} ({category})",
            entity_type="MERCHANT",
            institution=self.rng.choice(INSTITUTIONS),
            ifsc=f"MRDN0{self.rng.randrange(100000, 999999)}",
            city=city,
            country=country,
            balance=round(self.rng.uniform(4_00_000, 90_00_000), -3),
            opened_days_ago=self.rng.randint(900, 4200),
            is_dormant=False,
            customer_ref=None,
        )

    def make_external_account(
        self, entity_type: str = "BENEFICIARY", foreign: bool = False, young: bool = False
    ) -> AccountSpec:
        if foreign:
            city, country = self.rng.choice(FOREIGN_CITIES)
        else:
            city, country = self.rng.choice(CITIES)
        label = {
            "BENEFICIARY": "Beneficiary",
            "WALLET": "Wallet",
            "COMPANY": "Holdings",
            "MERCHANT": "Merchant",
        }.get(entity_type, "Account")
        return AccountSpec(
            ref=self.account_ref(),
            display_name=f"{self.person_name()} {label}"
            if entity_type == "BENEFICIARY"
            else f"{self.rng.choice(LAST_NAMES)} {label} Pvt Ltd",
            entity_type=entity_type,
            institution=self.rng.choice(INSTITUTIONS) if not foreign else "Correspondent Bank",
            ifsc=f"MRDN0{self.rng.randrange(100000, 999999)}",
            city=city,
            country=country,
            balance=round(self.rng.uniform(10_000, 30_00_000), -2),
            opened_days_ago=self.rng.randint(8, 120) if young else self.rng.randint(200, 3000),
            is_dormant=False,
            customer_ref=None,
            is_internal=not foreign,
        )

    # ------------------------------------------------------------------
    # Ordinary behavioural traffic
    # ------------------------------------------------------------------

    def customer_transactions(
        self,
        customer: CustomerSpec,
        merchant_accounts: Sequence[AccountSpec],
        beneficiary_pool: Sequence[AccountSpec],
        now: datetime,
        window_days: int,
    ) -> Tuple[List[TxnSpec], List[AccountSpec]]:
        """Generate one customer's transaction history from their archetype.

        Returns the transactions plus any new beneficiary accounts created for
        this customer, so new-counterparty signals have real rows behind them.
        """
        arch = customer.archetype
        primary = customer.accounts[0]
        txns: List[TxnSpec] = []
        new_accounts: List[AccountSpec] = []

        # The counterparty set this customer normally deals with
        regulars: List[AccountSpec] = self.rng.sample(
            list(merchant_accounts),
            k=min(len(merchant_accounts), max(2, customer.baseline_counterparties // 2)),
        )
        regulars += self.rng.sample(
            list(beneficiary_pool),
            k=min(len(beneficiary_pool), max(1, customer.baseline_counterparties // 2)),
        )

        months = max(window_days / 30.0, 1.0)
        total = int(customer.baseline_monthly_count * months)

        for index in range(total):
            # Position in the window: 0.0 = oldest, 1.0 = most recent
            progress = index / max(total - 1, 1)
            day = now - timedelta(days=window_days * (1 - progress))
            at = self.business_time(day)

            amount_median = arch.amount_median
            if arch.escalates and progress > 0.55:
                # Ramp over the last 45% of the window: a trajectory, not a step
                ramp = (progress - 0.55) / 0.45
                amount_median *= 1.0 + ramp * (arch.escalation_factor - 1.0)

            amount = self.lognormal_amount(amount_median, arch.amount_sigma)

            # Escalating, mule and structuring profiles acquire NEW beneficiaries late
            use_new_beneficiary = (
                arch.key in {"ESCALATING_RISK", "MULE_PASS_THROUGH", "STRUCTURING"}
                and progress > 0.6
                and self.rng.random() < 0.35
            )
            if use_new_beneficiary:
                account = self.make_external_account(
                    entity_type=self.rng.choice(["BENEFICIARY", "WALLET"]),
                    foreign=self.rng.random() < arch.international_rate,
                    young=True,
                )
                new_accounts.append(account)
                counterparty = account
            else:
                counterparty = self.rng.choice(regulars)

            international = counterparty.country != customer.country
            if not international and self.rng.random() < arch.international_rate:
                account = self.make_external_account(foreign=True, young=False)
                new_accounts.append(account)
                counterparty = account
                international = True

            # Structuring pins amounts just under the reporting threshold
            if arch.key == "STRUCTURING":
                amount = round(1_000_000 * self.rng.uniform(0.86, 0.985), -3)

            channel = self.pick_channel(amount)
            txns.append(
                TxnSpec(
                    ref=self.txn_ref(),
                    occurred_at=at,
                    sender_ref=primary.ref,
                    receiver_ref=counterparty.ref,
                    amount=amount,
                    channel=channel,
                    txn_type=(
                        "PAYMENT" if counterparty.entity_type == "MERCHANT" else "TRANSFER"
                    ),
                    city=customer.city,
                    country=counterparty.country if international else customer.country,
                    is_international=international,
                    narrative=self._narrative(counterparty),
                    typology=None,
                )
            )

            # Inbound credits: salary, settlements, refunds
            if self.rng.random() < 0.34:
                credit_amount = amount * self.rng.uniform(0.8, 1.6)
                source = self.rng.choice(list(beneficiary_pool))
                credit_at = at - timedelta(minutes=self.rng.randint(30, 900))
                txns.append(
                    TxnSpec(
                        ref=self.txn_ref(),
                        occurred_at=credit_at,
                        sender_ref=source.ref,
                        receiver_ref=primary.ref,
                        amount=round(credit_amount, -2),
                        channel=self.pick_channel(credit_amount),
                        txn_type="DEPOSIT",
                        city=customer.city,
                        country=customer.country,
                        is_international=False,
                        narrative="Inbound credit",
                    )
                )

        # Mule behaviour: pair each large credit with an immediate onward transfer
        if arch.key == "MULE_PASS_THROUGH":
            txns.extend(
                self._pass_through_pairs(customer, beneficiary_pool, now, window_days)
            )

        return txns, new_accounts

    def _narrative(self, counterparty: AccountSpec) -> str:
        if counterparty.entity_type == "MERCHANT":
            return f"Card/UPI purchase - {counterparty.display_name}"
        if counterparty.entity_type == "WALLET":
            return "Wallet top-up transfer"
        if counterparty.country != "India":
            return f"Cross-border remittance to {counterparty.country}"
        return "Funds transfer to beneficiary"

    def _pass_through_pairs(
        self,
        customer: CustomerSpec,
        beneficiary_pool: Sequence[AccountSpec],
        now: datetime,
        window_days: int,
    ) -> List[TxnSpec]:
        """Large credit in, near-identical debit out minutes later."""
        primary = customer.accounts[0]
        out: List[TxnSpec] = []
        for _ in range(self.rng.randint(4, 9)):
            day = now - timedelta(days=self.rng.uniform(1, min(window_days, 28)))
            at = self.business_time(day, night_bias=0.3)
            amount = self.lognormal_amount(customer.archetype.amount_median * 2.2, 0.5)
            source = self.rng.choice(list(beneficiary_pool))
            sink = self.rng.choice(list(beneficiary_pool))

            out.append(
                TxnSpec(
                    ref=self.txn_ref(),
                    occurred_at=at,
                    sender_ref=source.ref,
                    receiver_ref=primary.ref,
                    amount=amount,
                    channel=self.pick_channel(amount),
                    txn_type="DEPOSIT",
                    city=customer.city,
                    country=customer.country,
                    is_international=False,
                    narrative="Large inbound credit",
                    typology="PASS_THROUGH",
                )
            )
            # Forwarded onward within minutes, minus a small skim
            forwarded = round(amount * self.rng.uniform(0.94, 0.99), -2)
            out.append(
                TxnSpec(
                    ref=self.txn_ref(),
                    occurred_at=at + timedelta(minutes=self.rng.randint(2, 26)),
                    sender_ref=primary.ref,
                    receiver_ref=sink.ref,
                    amount=forwarded,
                    channel=self.pick_channel(forwarded),
                    txn_type="TRANSFER",
                    city=customer.city,
                    country=customer.country,
                    is_international=False,
                    narrative="Onward transfer",
                    typology="PASS_THROUGH",
                )
            )
        return out

    # ------------------------------------------------------------------
    # Explicit laundering typologies (what the graph engine should find)
    # ------------------------------------------------------------------

    def layering_ring(
        self, now: datetime, depth: int = 4, principal: Optional[float] = None
    ) -> Tuple[List[AccountSpec], List[TxnSpec], Dict[str, str]]:
        """source -> intermediaries -> convergence, plus a parallel leg.

        This is the canonical structure from the specification:
            A -> B -> {C, D} -> E
        """
        accounts: List[AccountSpec] = []
        roles: Dict[str, str] = {}

        source = self.make_external_account("COMPANY", young=False)
        accounts.append(source)
        roles[source.ref] = "SOURCE"

        chain = []
        for _ in range(depth):
            node = self.make_external_account("BENEFICIARY", young=True)
            accounts.append(node)
            roles[node.ref] = "INTERMEDIARY"
            chain.append(node)

        convergence = self.make_external_account("COMPANY", young=True)
        accounts.append(convergence)
        roles[convergence.ref] = "CONVERGENCE"

        txns: List[TxnSpec] = []
        amount = principal or self.lognormal_amount(4_500_000, 0.4)
        at = self.business_time(now - timedelta(days=self.rng.uniform(2, 20)), night_bias=0.35)
        previous = source

        for hop in chain:
            txns.append(
                TxnSpec(
                    ref=self.txn_ref(),
                    occurred_at=at,
                    sender_ref=previous.ref,
                    receiver_ref=hop.ref,
                    amount=round(amount, -2),
                    channel="RTGS" if amount >= 2_00_000 else "IMPS",
                    txn_type="TRANSFER",
                    city=previous.city,
                    country=previous.country,
                    is_international=previous.country != hop.country,
                    narrative="Inter-account transfer",
                    typology="LAYERED",
                )
            )
            # Each hop retains 1-3% and forwards within the hour
            amount *= 1.0 - self.rng.uniform(0.01, 0.03)
            at += timedelta(minutes=self.rng.randint(3, 48))
            previous = hop

        txns.append(
            TxnSpec(
                ref=self.txn_ref(),
                occurred_at=at,
                sender_ref=previous.ref,
                receiver_ref=convergence.ref,
                amount=round(amount, -2),
                channel="RTGS",
                txn_type="TRANSFER",
                city=previous.city,
                country=previous.country,
                is_international=previous.country != convergence.country,
                narrative="Consolidation transfer",
                typology="LAYERED",
            )
        )

        # Parallel leg: the first hop also splits to a branch that reconverges
        branch = self.make_external_account("WALLET", young=True)
        accounts.append(branch)
        roles[branch.ref] = "INTERMEDIARY"
        leg = round(amount * self.rng.uniform(0.34, 0.46), -2)
        split_at = at + timedelta(minutes=self.rng.randint(4, 20))
        txns.append(
            TxnSpec(
                ref=self.txn_ref(),
                occurred_at=split_at,
                sender_ref=chain[0].ref,
                receiver_ref=branch.ref,
                amount=leg,
                channel="IMPS",
                txn_type="TRANSFER",
                city=chain[0].city,
                country=chain[0].country,
                is_international=False,
                narrative="Split transfer",
                typology="LAYERED",
            )
        )
        txns.append(
            TxnSpec(
                ref=self.txn_ref(),
                occurred_at=split_at + timedelta(minutes=self.rng.randint(5, 30)),
                sender_ref=branch.ref,
                receiver_ref=convergence.ref,
                amount=round(leg * 0.98, -2),
                channel="IMPS",
                txn_type="TRANSFER",
                city=branch.city,
                country=branch.country,
                is_international=branch.country != convergence.country,
                narrative="Consolidation transfer",
                typology="LAYERED",
            )
        )
        return accounts, txns, roles

    def circular_ring(
        self, now: datetime, size: int = 5
    ) -> Tuple[List[AccountSpec], List[TxnSpec], Dict[str, str]]:
        """A closed loop that returns most of the principal to its origin."""
        accounts = [
            self.make_external_account(
                self.rng.choice(["COMPANY", "BENEFICIARY", "WALLET"]),
                young=self.rng.random() < 0.6,
            )
            for _ in range(size)
        ]
        roles = {a.ref: "CYCLE_MEMBER" for a in accounts}

        txns: List[TxnSpec] = []
        amount = self.lognormal_amount(2_600_000, 0.35)
        at = self.business_time(now - timedelta(days=self.rng.uniform(3, 25)), night_bias=0.3)

        for index in range(size):
            sender = accounts[index]
            receiver = accounts[(index + 1) % size]
            txns.append(
                TxnSpec(
                    ref=self.txn_ref(),
                    occurred_at=at,
                    sender_ref=sender.ref,
                    receiver_ref=receiver.ref,
                    amount=round(amount, -2),
                    channel="RTGS" if amount >= 2_00_000 else "NEFT",
                    txn_type="TRANSFER",
                    city=sender.city,
                    country=sender.country,
                    is_international=sender.country != receiver.country,
                    narrative="Inter-company settlement",
                    typology="CIRCULAR",
                )
            )
            amount *= 1.0 - self.rng.uniform(0.008, 0.024)
            at += timedelta(minutes=self.rng.randint(20, 260))
        return accounts, txns, roles

    def smurfing_fan_in(
        self, now: datetime, payers: int = 12
    ) -> Tuple[List[AccountSpec], List[TxnSpec], Dict[str, str]]:
        """Many near-identical deposits converging, then swept onward."""
        collector = self.make_external_account("BENEFICIARY", young=True)
        onward = self.make_external_account(
            "COMPANY", foreign=self.rng.random() < 0.45, young=True
        )
        accounts = [collector, onward]
        roles = {collector.ref: "CONVERGENCE", onward.ref: "SINK"}

        txns: List[TxnSpec] = []
        ticket = self.lognormal_amount(165_000, 0.12)
        at = self.business_time(now - timedelta(days=self.rng.uniform(1, 18)), night_bias=0.28)

        for _ in range(payers):
            payer = self.make_external_account("BENEFICIARY", young=self.rng.random() < 0.5)
            accounts.append(payer)
            roles[payer.ref] = "PARTICIPANT"
            amount = round(ticket * self.rng.uniform(0.97, 1.03), -2)
            txns.append(
                TxnSpec(
                    ref=self.txn_ref(),
                    occurred_at=at,
                    sender_ref=payer.ref,
                    receiver_ref=collector.ref,
                    amount=amount,
                    channel=self.rng.choice(["IMPS", "UPI", "NEFT"]),
                    txn_type="DEPOSIT",
                    city=payer.city,
                    country=payer.country,
                    is_international=False,
                    narrative="Cash-equivalent deposit",
                    typology="SMURFING",
                )
            )
            at += timedelta(minutes=self.rng.randint(1, 22))

        sweep = round(ticket * payers * self.rng.uniform(0.96, 0.99), -2)
        txns.append(
            TxnSpec(
                ref=self.txn_ref(),
                occurred_at=at + timedelta(minutes=self.rng.randint(5, 55)),
                sender_ref=collector.ref,
                receiver_ref=onward.ref,
                amount=sweep,
                channel="RTGS",
                txn_type="TRANSFER",
                city=collector.city,
                country=collector.country,
                is_international=collector.country != onward.country,
                narrative="Aggregate sweep transfer",
                typology="SMURFING",
            )
        )
        return accounts, txns, roles

    def fan_out_dispersion(
        self, now: datetime, receivers: int = 11
    ) -> Tuple[List[AccountSpec], List[TxnSpec], Dict[str, str]]:
        """One funded account splitting value across many fresh accounts fast."""
        funder = self.make_external_account("COMPANY", young=False)
        distributor = self.make_external_account("BENEFICIARY", young=True)
        accounts = [funder, distributor]
        roles = {funder.ref: "SOURCE", distributor.ref: "DISTRIBUTOR"}

        principal = self.lognormal_amount(5_200_000, 0.3)
        at = self.business_time(now - timedelta(days=self.rng.uniform(1, 16)), night_bias=0.3)

        txns = [
            TxnSpec(
                ref=self.txn_ref(),
                occurred_at=at,
                sender_ref=funder.ref,
                receiver_ref=distributor.ref,
                amount=round(principal, -2),
                channel="RTGS",
                txn_type="TRANSFER",
                city=funder.city,
                country=funder.country,
                is_international=False,
                narrative="Funding transfer",
                typology="FAN_OUT",
            )
        ]

        slice_amount = principal / receivers
        at += timedelta(minutes=self.rng.randint(3, 25))
        for _ in range(receivers):
            receiver = self.make_external_account(
                self.rng.choice(["BENEFICIARY", "WALLET"]),
                foreign=self.rng.random() < 0.22,
                young=True,
            )
            accounts.append(receiver)
            roles[receiver.ref] = "PARTICIPANT"
            amount = round(slice_amount * self.rng.uniform(0.95, 1.05), -2)
            txns.append(
                TxnSpec(
                    ref=self.txn_ref(),
                    occurred_at=at,
                    sender_ref=distributor.ref,
                    receiver_ref=receiver.ref,
                    amount=amount,
                    channel=self.pick_channel(amount),
                    txn_type="TRANSFER",
                    city=distributor.city,
                    country=(
                        receiver.country
                        if receiver.country != "India"
                        else distributor.country
                    ),
                    is_international=receiver.country != distributor.country,
                    narrative="Onward distribution",
                    typology="FAN_OUT",
                )
            )
            at += timedelta(minutes=self.rng.randint(1, 11))
        return accounts, txns, roles

    def legitimate_merchant_collection(
        self, now: datetime, payers: int = 16
    ) -> Tuple[List[AccountSpec], List[TxnSpec], Dict[str, str]]:
        """Hard negative: a real merchant collecting from many customers.

        Wide amount spread and arrivals spread over weeks - structurally similar
        to smurfing but legitimate. Present so the graph layer has to actually
        discriminate rather than flagging every fan-in.
        """
        merchant = self.make_external_account("MERCHANT", young=False)
        settlement = self.make_external_account("COMPANY", young=False)
        accounts = [merchant, settlement]
        roles: Dict[str, str] = {}

        txns: List[TxnSpec] = []
        for _ in range(payers):
            payer = self.make_external_account("BENEFICIARY", young=False)
            accounts.append(payer)
            amount = self.lognormal_amount(9_500, 0.95)
            at = self.business_time(now - timedelta(days=self.rng.uniform(1, 60)))
            txns.append(
                TxnSpec(
                    ref=self.txn_ref(),
                    occurred_at=at,
                    sender_ref=payer.ref,
                    receiver_ref=merchant.ref,
                    amount=amount,
                    channel=self.rng.choice(["UPI", "CARD", "WALLET"]),
                    txn_type="PAYMENT",
                    city=payer.city,
                    country=payer.country,
                    is_international=False,
                    narrative=f"Retail purchase - {merchant.display_name}",
                )
            )

        # Weekly settlement sweeps, days apart, retaining a real margin
        for week in range(3):
            amount = self.lognormal_amount(320_000, 0.3)
            txns.append(
                TxnSpec(
                    ref=self.txn_ref(),
                    occurred_at=self.business_time(now - timedelta(days=7 * (week + 1))),
                    sender_ref=merchant.ref,
                    receiver_ref=settlement.ref,
                    amount=amount,
                    channel="NEFT",
                    txn_type="TRANSFER",
                    city=merchant.city,
                    country=merchant.country,
                    is_international=False,
                    narrative="Weekly merchant settlement",
                )
            )
        return accounts, txns, roles

    # ------------------------------------------------------------------
    # Orders for the transaction integrity gateway
    # ------------------------------------------------------------------

    def make_order(
        self,
        customer: CustomerSpec,
        merchant: AccountSpec,
        now: datetime,
        status: str = "AWAITING_PAYMENT",
        amount: Optional[float] = None,
    ) -> OrderSpec:
        merchant_name, category = self.rng.choice(MERCHANTS)
        value = amount or self.lognormal_amount(
            max(customer.baseline_avg_amount, 2_000), 0.5
        )
        return OrderSpec(
            ref=self.order_ref(),
            customer_ref=customer.ref,
            merchant_name=merchant.display_name,
            merchant_account_ref=merchant.ref,
            description=f"{category} order - {merchant_name}",
            authorized_amount=round(value, 2),
            currency="INR",
            status=status,
            created_at=self.business_time(now - timedelta(days=self.rng.uniform(0, 6))),
        )
