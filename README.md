# Meridian AML — Financial Surveillance & Transaction Security Platform

An academic/prototype **Intelligent Anti-Money-Laundering and Transaction Surveillance
System**. It is not a "fraud detection website": it answers three distinct questions with
three distinct mechanisms, and keeps them architecturally separate.

| Question | Layer | Mechanism |
|---|---|---|
| *Was the payment request modified before it reached the provider?* | **Transaction integrity** | Deterministic server-side comparison against the authoritative order amount + HMAC digest |
| *Is this customer becoming risky, before the transaction is authorised?* | **Proactive AML** | Trained RandomForest over 18 behavioural features + configurable rules engine |
| *Do settled transactions form suspicious patterns or laundering networks?* | **Reactive AML + GNN** | Five behavioural detectors + graph typology detection + a trained graph neural network |

```
                    FINANCIAL TRANSACTION
                            │
                            ▼
                 TRANSACTION INTEGRITY  ── fails ──▶ BLOCKED (no AML scoring, nothing forwarded)
                            │
                            ▼
                    PROACTIVE AML          (features → model → rules → composite score)
                            │
                            ▼
                     RISK DECISION         ALLOW / MONITOR / REVIEW / BLOCK
                            │
                            ▼
                       PAYMENT             (server-authorised amount only)
                            │
                            ▼
                   REACTIVE MONITORING     (5 typology detectors)
                            │
                            ▼
                      GRAPH ENGINE         (Tarjan SCC, layering DFS, fan/smurf analysis)
                            │
                            ▼
                           GNN             (node / edge / subgraph heads)
                            │
                            ▼
                SUSPICIOUS NETWORK / RING
                            │
                            ▼
                      INVESTIGATOR  ──▶  INVESTIGATION  ──▶  AUDIT TRAIL
```

---

## 1. Project structure

```
aml-platform/
├── backend/
│   ├── app/
│   │   ├── api/v1/          auth, transactions, customers, alerts, networks,
│   │   │                    investigations, rules, system (dashboard/audit/models/demo)
│   │   ├── core/            config (env-driven), security (bcrypt + JWT), deps (RBAC)
│   │   ├── db/              engine, session, declarative base
│   │   ├── models/          14 ORM entities + enums
│   │   ├── schemas/         Pydantic request/response contracts
│   │   ├── services/        integrity, decision, feature, risk, reactive, network,
│   │   │                    alert, investigation, audit, dashboard, customer,
│   │   │                    model, demo
│   │   ├── rules/           rule catalogue (data) + evaluation engine
│   │   ├── ml/              feature spec, model interface, RF trainer, registry
│   │   ├── gnn/             engine interface, PyTorch GNN, trainer, analytic
│   │   │                    fallback, explanation layer, registry
│   │   ├── graph/           types/featurisation, builder (DB→graph), patterns
│   │   │                    (typology detection), synthetic (training graphs)
│   │   └── main.py
│   ├── seed/                seed.py + generators.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── src/
│       ├── components/      shared UI primitives
│       ├── pages/           18 pages
│       ├── layouts/         app shell (sidebar + header)
│       ├── charts/          Recharts components
│       ├── graph/           React Flow network visualisation
│       ├── context/         auth + toast
│       ├── hooks/           data fetching
│       ├── services/        API client
│       └── utils/           formatters + semantic risk palette
├── database/                SQLite file lands here
└── README.md
```

---

## 2. Setup

### Prerequisites
Python 3.10+, Node 18+.

### Backend

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env      # Windows: copy .env.example .env
```

Generate a real secret key and put it in `.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### Environment variables

All configuration is environment-driven; nothing secret is hard-coded or shipped to the
browser. See `backend/.env.example` for the annotated list.

| Variable | Default | Purpose |
|---|---|---|
| `ENVIRONMENT` | `demo` | `demo` \| `development` \| `production` |
| `DATABASE_URL` | `sqlite:///../database/aml.db` | SQLAlchemy URL (PostgreSQL supported, see below) |
| `SECRET_KEY` | *dev placeholder* | JWT signing **and** the order-integrity HMAC key. Refused at boot if left as the placeholder while `ENVIRONMENT=production` |
| `JWT_ALGORITHM` | `HS256` | Token algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | Token lifetime |
| `BCRYPT_ROUNDS` | `12` | Password hashing cost |
| `CORS_ORIGINS` | `http://localhost:5173,…` | Comma-separated allow-list |
| `RISK_THRESHOLD_MEDIUM` / `_HIGH` / `_CRITICAL` | `35` / `60` / `85` | Decision bands (visible on the Settings page) |
| `ML_MODEL_PATH` | `app/ml/artifacts/proactive_rf.joblib` | RandomForest artifact |
| `GNN_MODEL_PATH` | `app/gnn/artifacts/aml_gnn.pt` | GNN checkpoint |
| `GNN_ENGINE` | `auto` | `auto` \| `torch` (require the trained GNN) \| `analytic` (force the untrained fallback) |

### Database

**SQLite (default, zero setup)** — the file is created automatically at
`database/aml.db`; `PRAGMA foreign_keys=ON` and WAL mode are enabled.

**PostgreSQL (production-style)**:

```bash
createdb aml_db
createuser aml_user --pwprompt
```
```env
DATABASE_URL=postgresql+psycopg2://aml_user:aml_password@localhost:5432/aml_db
```

The same code runs on both — time-bucketing in the dashboard is dialect-aware
(`strftime` on SQLite, `to_char` on PostgreSQL).

### Seed the database and train the models

```bash
cd backend
python -m seed.seed
```

This one command creates the schema, **trains both models**, generates the mock data and
prints the demo credentials. Useful flags:

```bash
python -m seed.seed --help
python -m seed.seed --no-train         # reuse existing model artifacts (much faster)
python -m seed.seed --small            # smaller dataset for faster iteration
python -m seed.seed --keep             # clear rows instead of dropping tables
python -m seed.seed --seed 7           # different RNG seed
```

By default the seed **drops and recreates every table**. There are no migrations yet,
so after a model/schema change re-run the seed without `--keep` to pick up new columns.

### Tests

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest tests
```

The suite uses its own throwaway SQLite file and never touches `database/aml.db`.

### Run

```bash
# terminal 1 — backend  (http://127.0.0.1:8000, docs at /api/docs)
cd backend
uvicorn app.main:app --reload --port 8000

# terminal 2 — frontend (http://localhost:5173)
cd frontend
npm install
npm run dev
```

Vite proxies `/api` to `127.0.0.1:8000`, so no CORS configuration is needed in development.

### Demo credentials

| Username | Password | Role | Can |
|---|---|---|---|
| `analyst` | `Analyst@2026` | ANALYST | View transactions/customers, review alerts, investigate networks, add notes |
| `admin` | `Admin@2026` | ADMIN | Everything above **plus** manage users, configure rules, read audit logs, change settings |

Additional analyst accounts (`analyst2`, `analyst3`) share the analyst password.

---

## 3. The transaction integrity gateway

**The security property:** the authoritative amount is read from
`orders.authorized_amount` in the database. The client-supplied amount is treated as an
untrusted *claim* — it is used only for comparison and forensic logging, and is never

- used as the amount to charge,
- written into a transaction as the settled amount, or
- forwarded to a payment provider.

So a client that rewrites ₹8,000 into ₹80,000 cannot change what would be charged. It can
only produce an integrity failure and a blocked payment:

```
TRANSACTION INTEGRITY FAILURE
Expected amount : INR 8,000.00     (server-side order record — authoritative)
Received amount : INR 80,000.00    (client claim — untrusted)
Mismatch        : INR 72,000.00  (900.0%)
ACTION          : BLOCKED
```

Five checks run in order, and **any** failure is a hard gate — AML scoring is skipped
entirely, because "was this tampered with" and "is this customer suspicious" are different
questions with different remedies:

1. **Order exists** — no server-side order means there is no authoritative amount to
   validate against, so the request is refused.
2. **HMAC digest valid** — a digest over `(order_ref, amount, currency, customer_ref)`
   keyed with `SECRET_KEY` detects tampering with the stored row itself.
3. **Order is payable** — blocks duplicate and replayed payment attempts.
4. **Customer owns the order.**
5. **Currency and amount match** (amount compared with a 0.01 tolerance).

Try it on the **Security Gateway** page: pick an order, press *Tamper ×10*, and submit.
`POST /api/transactions/validate` runs the integrity check alone;
`POST /api/transactions/decision` runs the whole pipeline.

---

## 4. The proactive AML pipeline

Nine ordered steps, visible step-by-step in the UI:

```
1. Validate order                  ─┐
2. Retrieve server-side amount      │ hard gate — a failure here stops everything
3. Validate amount integrity       ─┘
4. Calculate behavioural features   (from the customer's real history, server-side)
5. Run the proactive risk model
6. Generate the composite risk score
7. Apply decision rules             (configurable thresholds)
8. Allow / Monitor / Review / Block
9. Record an audit event
```

**Features (18).** `app/ml/features.py` is the single source of truth for the model's input
space — the trainer, the live extractor, the explanation layer and the Model Insights page
all read from it, so features cannot drift between training and inference. They cover
amount deviation from the customer's own baseline, frequency ratio, peak velocity, burst
concentration, counterparty counts and growth, rapid-movement (pass-through) ratio,
threshold-adjacent structuring, round-amount ratio, cross-border and elevated-jurisdiction
exposure, relationship age, prior alerts, dormancy reactivation and PEP status.

**Scoring.** The composite blends two independent sources so an institution can reason
about and override the automation:

```
score = clamp( 0.45 × 100·P(model) + 0.55 × rule_points , 0, 100 )
```

**Explainability.** The score is decomposed into factors whose contributions **sum to the
score** — the breakdown reconciles rather than being decorative:

```
Risk factors                                            contributions total 60.7 of 60.7
+28.1  Higher-risk jurisdiction exposure   62% of value touches an elevated-risk jurisdiction (limit 25%)
+12.1  Transaction amount threshold        Transaction value of INR 2,180,400 exceeds the INR 1,000,000 threshold
+10.1  New beneficiary activity            11 new beneficiaries detected in 30 days (limit 5)
 +5.9  Prior alert history                 3 prior alerts on this customer (threshold 2)
 ...
```

Model contributions come from **occlusion attribution**: each feature is reset to its
neutral baseline and the drop in predicted probability is measured. That is a real
interrogation of the fitted model, not a hand-written score table — and it is not exact
Shapley, which the Model Insights page says explicitly. All 19 forward passes are batched
into one `predict_proba` call. Where a rule and a model attribution describe the same
signal they are merged, so an investigator never sees the same finding twice.

**Decision bands** (configurable): `LOW → Allow`, `MEDIUM → Monitor`, `HIGH → Review/hold`,
`CRITICAL → Block/escalate`.

---

## 5. The reactive + GNN pipeline

### Reactive detectors

Five detectors run over settled transactions, each reading its threshold from the rules
engine and each producing a narrative with the measurements behind it:

| Detector | Example finding |
|---|---|
| Unusual amount | "Customer normally transacts around INR 12.4 K. Observed: INR 8.51 L." |
| High velocity | "17 transactions within 14 minutes." |
| Rapid movement of funds | "INR 10.2 L received, INR 9.81 L transferred out 2 minutes later." |
| Multiple counterparties | "1 account paying out to 18 new recipients." |
| Behavioural anomaly | "Average moved from INR 15.1 K to INR 1.82 L (+1104%)." |

### Graph engine

`app/graph/patterns.py` implements real graph algorithms on the directed money-flow graph:

- **Circular flow** — Tarjan strongly-connected components (iterative), scored on value
  conservation around the loop.
- **Layering chains** — bounded-depth DFS along temporally-ordered, rapid, *value-continuous*
  hops through accounts that retain almost nothing.
- **Fan-out / fan-in / smurfing** — degree and burst analysis, **gated on amount uniformity
  or burst speed** so ordinary merchant collections and payroll runs do not qualify.
- **Clustering** — overlapping candidates are merged so one cluster becomes one case.

Structure detection is kept explicit and separate from the GNN so an investigator can
always be told *which topology* triggered a cluster, in graph terms they can verify by eye.

### The GNN

`app/gnn/torch_gnn.py` — a genuine graph neural network in plain PyTorch (no PyTorch
Geometric dependency; sparse aggregation via `index_add_`).

- **Encoder**: 3-layer directed, value-weighted GraphSAGE. Each layer aggregates
  *separately* over inbound and outbound neighbourhoods, because in a money-flow graph "who
  paid me" and "who I paid" are different signals — a collapsed undirected mean would
  destroy exactly the asymmetry that distinguishes a collection account from a distributor.
  Messages are weighted by log-scaled transfer amount.
- **Three heads**: node risk (node classification), edge risk (both endpoint embeddings +
  6 edge features), and subgraph risk (readout over mean+max pooled embeddings).
- **Features**: 16 node features and 6 edge features, computed by `build_snapshot()` —
  the *same function* used by the training-graph generator and the live database builder,
  which is what guarantees the feature space cannot drift.

Final network risk blends the learned and structural views:
`0.6 × GNN_graph_score + 0.4 × structural_confidence`, flagged suspicious at ≥ 55.

Transactions inside a flagged structure have their risk lifted to the GNN's edge score and
are marked `scored_by = NETWORK` — a transfer sitting inside a laundering ring is riskier
than its standalone features suggest, which is the entire point of the network layer.

### Swapping the engine

Both models sit behind interfaces (`ProactiveRiskModel`, `GNNInferenceEngine`) resolved by
registries. To use PyTorch Geometric, implement `GNNInferenceEngine` and register it —
nothing else changes. `GNN_ENGINE=analytic` forces the untrained fallback for comparison.

### The window GNN: GraphSAGE trained on IBM AMLworld

The network layer's learned model. It scores **one account at a time from its
neighbourhood** and is trained and evaluated on **IBM AMLworld** (Altman et al.,
NeurIPS 2023), an independent public AML benchmark, rather than on this project's own
generator. Plain-language guide: [`docs/GNN_EXPLAINED.md`](docs/GNN_EXPLAINED.md).
Results (generated from the run reports): [`docs/GNN_RESULTS.md`](docs/GNN_RESULTS.md).

| Step | What | Code |
|---|---|---|
| R1 | 7-day, 3-hop neighbourhood **windows**; each account's features computed from all its activity, so it looks the same in every window | `app/graph/window.py`, `app/graph/features_v2.py`, `app/graph/db_source.py` |
| R2 | AMLworld loader, **time-based** 60/20/20 split, weighted negative sampling, baselines (gradient boosting, logistic regression) vs the GNN | `app/datasets/amlworld.py`, `app/gnn/window_dataset.py`, `app/gnn/r2.py` |
| R3 | **GraphSAGE ablation** - A plain, B directed, C edge-aware; the app's model is chosen on validation only | `app/gnn/sage.py`, `app/gnn/r3.py` |
| R4 | **Explanations** by occlusion (which transfers the score rests on) and a fidelity test | `app/gnn/explain_v2.py`, `app/gnn/r4.py` |
| R5 | In the app: settled payments are scored in the background, **Run GNN scoring** on the Network page, alerts with the transfers behind them | `app/services/gnn_v2_service.py`, `GET/POST /api/networks/gnn/*` |
| R6 | Results tables generated from the reports | `app/gnn/report_md.py` |

**Reproduce** (CPU is enough; a full run takes a few hours, mostly training 5 seeds per model):

1. Download two files of the **HI-Small** variant from Kaggle, *IBM Transactions for
   Anti Money Laundering (AML)*: `HI-Small_Trans.csv` (~0.5 GB) and
   `HI-Small_Patterns.txt`, into `data/amlworld/` (git-ignored).
2. Run:

```bash
cd backend
python -m app.gnn.r2 --trans ../data/amlworld/HI-Small_Trans.csv --patterns ../data/amlworld/HI-Small_Patterns.txt --until 2022-09-10
python -m app.gnn.r3 --trans ../data/amlworld/HI-Small_Trans.csv --patterns ../data/amlworld/HI-Small_Patterns.txt --until 2022-09-10
python -m app.gnn.r4 --trans ../data/amlworld/HI-Small_Trans.csv --patterns ../data/amlworld/HI-Small_Patterns.txt --until 2022-09-10
python -m app.gnn.report_md
```

R3 exports the selected model to `backend/app/gnn/artifacts/aml_gnn_v2.pt` (with a
readable `.meta.json`); the app picks it up on the next start, and `python -m seed.seed`
scores the demo data with it. Without it, the app runs as before and the GNN panel says
the model is not trained.

`--until 2022-09-10` matters: after 10 Sept HI-Small has only ~1.1K transfers, ~59% of them
laundering (the simulator keeps laundering after normal activity stops). Left in, they
fall in the test split and inflate every model's score. Negatives are subsampled and
weighted, so precision, PR-AUC and alert rate estimate the result on *all* active
accounts at the real class balance (~0.3% positive).

**Domain note.** AMLworld is multi-currency, US-style data; this platform's demo data is
INR / UPI. Features are currency-neutral (amounts converted to USD, payment channels
mapped to shared payment rails), but the accuracy figures are AMLworld results - on the
demo data the model illustrates the mechanism.

---

## 6. What is real and what is simulated

This is the section to read before trusting any number in the UI.

### Genuinely real

- **The RandomForest is really fitted.** 13,500 training rows, held-out 25% stratified
  split. Reported metrics come from that split: **accuracy 0.932, precision 0.934,
  recall 0.871, F1 0.901, ROC-AUC 0.916.**
- **The window GNN is really trained and tested on independent data**: GraphSAGE on IBM
  AMLworld HI-Small with a time-based split, compared against gradient boosting and
  logistic regression, several seeds, thresholds chosen on validation. Results:
  [`docs/GNN_RESULTS.md`](docs/GNN_RESULTS.md).
- **The legacy structural GNN** (`app/gnn/torch_gnn.py` checkpoint `aml_gnn.pt`) is really
  trained by backpropagation on 848 *self-generated* graphs; its held-out node F1 0.949 is
  measured on that generator only (see below).
- **Occlusion attributions** are real model interrogations.
- **Graph algorithms** (Tarjan SCC, DFS chains, value-weighted PageRank in the fallback)
  are real implementations, not decoration.
- **Every metric on the Model Insights page** is read from the trained artifacts. When no
  artifact is loaded the page reports the component as untrained and shows **no** metrics,
  rather than plausible-looking placeholders.
- **All API/UI logic** — integrity gating, RBAC, audit trail, alert and case lifecycles,
  dashboard aggregates — is real and operates on the database.

### Simulated, and why

- **The training labels.** A production AML model is trained on confirmed SAR/STR outcomes.
  No such ground truth exists for a prototype.
  - The RandomForest uses **archetype weak labels with 7% deliberate label noise**, sampled
    from overlapping distributions. Two archetypes (`SME_HIGH_VALUE_LEGIT`,
    `VOLATILE_LEGIT`) are deliberate **hard negatives** — big, frequent, cross-border but
    legitimate — so the model cannot separate classes on transaction size alone.
  - The legacy structural GNN uses **structural ground truth by construction**: topologies are injected into
    generated graphs, so node/edge/graph labels are known exactly. Benign look-alikes
    (flash-sale merchant collections, uniform contractor payout runs, same-day thin-margin
    trade settlements) are included as hard negatives, and **every negative graph contains
    at least one** — without them the task degenerates into counting node degree.

  So the honest claim is: **the legacy GNN has really learned to recognise laundering
  *topologies*. It has not learned, and cannot claim, to identify money launderers.**
  This is why the window GNN is trained and evaluated on AMLworld instead.
  - **IBM AMLworld** is itself simulated (by an independent team, from a virtual economy):
    no public dataset of real, labelled bank transactions exists, because of privacy law
    and the confidentiality of suspicious-transaction reports.
- **All customer, account and transaction data** is generated. No real financial data.
- **The payment provider.** There is no integration. Where a provider SDK call would go,
  the API returns an explicit `payment_provider_note` saying so, and the UI displays it.
  Nothing in the product can be mistaken for a real settlement.

### Read the node metric, not the other two

Edge scoring (F1 0.999) and subgraph detection (accuracy 1.000) both saturate, and that is
an artefact of label construction rather than exceptional capability: an edge is positive
exactly when both endpoints are in an injected structure, which the endpoint embeddings
already encode; and the graph label is "contains ≥1 injected typology", which reduces to an
OR over node predictions. **Node classification (~0.95 F1) is the only one of the three that
is genuinely discriminative on this dataset.** This caveat ships inside the checkpoint and
is displayed on the Model Insights page.

---

## 7. Security

- **Never trust client financial values** — see §3. The gateway is the concrete
  demonstration.
- **Passwords**: bcrypt, per-password random salt, configurable cost. Plaintext is never
  stored, logged or returned.
- **Auth**: short-lived HS256 JWTs; token in `sessionStorage` only (never a cookie or
  `localStorage`); a 401 from any call drops the session immediately.
- **RBAC**: capability matrix held server-side. Every protected endpoint re-checks with a
  `RequirePermission` dependency. The permission list sent to the browser only hides
  controls — it grants nothing. (Verified: an analyst calling `/api/audit-logs` gets 403.)
- **Input validation**: Pydantic schemas with bounds, patterns and enums on every endpoint.
- **No account enumeration**: unknown user and wrong password return the same message, and
  both are audit-logged.
- **Audit trail**: append-only; the actor always comes from the verified token, never the
  request body, so a client cannot attribute an action to someone else.
- **Secrets**: environment variables only. The frontend holds no secret, no model artifact
  and no database credential; it reaches data exclusively through the API. Production boot
  fails if `SECRET_KEY` is still the placeholder.
- **Self-lockout guard**: an admin cannot disable their own account.

---

## 8. API

Interactive docs at `http://127.0.0.1:8000/api/docs`. 51 endpoints; the core set:

```
POST   /api/auth/login                     POST   /api/transactions/validate
GET    /api/auth/me                        POST   /api/transactions/analyze
POST   /api/auth/logout                    POST   /api/transactions/decision
GET    /api/auth/users            (admin)  GET    /api/transactions
POST   /api/auth/users            (admin)  GET    /api/transactions/{txn_ref}
PATCH  /api/auth/users/{username} (admin)  GET    /api/transactions/orders

GET    /api/customers                      GET    /api/networks
GET    /api/customers/{ref}                GET    /api/networks/{ref}
GET    /api/customers/{ref}/risk           GET    /api/networks/{ref}/graph
GET    /api/customers/proactive-overview   GET    /api/networks/{ref}/assessment
                                           GET    /api/networks/graph
GET    /api/alerts                         GET    /api/networks/node/{account_ref}
GET    /api/alerts/{ref}                   POST   /api/networks/analyse
GET    /api/alerts/stats
PATCH  /api/alerts/{ref}/status            GET    /api/investigations
POST   /api/alerts/{ref}/assign            POST   /api/investigations
GET    /api/reactive/overview              GET    /api/investigations/{case_ref}
POST   /api/reactive/run                   POST   /api/investigations/{ref}/notes
                                           PATCH  /api/investigations/{ref}/status
GET    /api/rules                          POST   /api/investigations/{ref}/assign
GET    /api/rules/{code}
POST   /api/rules                 (admin)  GET    /api/dashboard/overview
PATCH  /api/rules/{code}          (admin)  GET    /api/models/insights
                                           GET    /api/audit-logs        (admin)
GET    /api/health                         GET    /api/audit-logs/actions (admin)
GET    /api/settings                       POST   /api/demo/run
                                           GET    /api/demo/scenarios
```

Errors use a consistent envelope: `{"error": {"code", "message", "field"}}`.

---

## 9. Mock data

`python -m seed.seed` generates, by default:

- **120 customers** across 8 behavioural archetypes — 4 legitimate (including two
  deliberate hard negatives) and 4 elevated-risk (escalating, structuring, mule
  pass-through, cross-border).
- **~18,000 transactions** over a 180-day window with realistic channel mix, Indian city
  distribution and diurnal timing.
- **Injected laundering structures**: layering chains (source → intermediaries →
  convergence), circular rings, fan-out dispersion and smurfing convergence.
- **~150 alerts** across the reactive and network layers, **10 investigations** with notes
  and timelines, historical weekly risk assessments per customer, and a populated audit log.
- **32 detected clusters, 11 flagged suspicious** (highest scoring 99.6/100).

Risk distribution after seeding separates the archetypes meaningfully — legitimate
archetypes average 7–23/100 while elevated ones reach 38–62/100.

---

## 10. Run the whole story

The **Run AML Demo** page executes the complete narrative against the live database using
the same services the individual pages call. Each step links to where you can verify it.

`LAYERED_RING` (13 steps) — a payment clears, then the network layer surfaces a ring:

```
 1 PASS  CLIENT        Customer initiates payment            INR 57,800 to Kirana Direct
 2 PASS  INTEGRITY     Integrity validation                  verified against server record
 3 WARN  PROACTIVE     Proactive AML analyses the customer   35.6/100 MEDIUM
 4 PASS  PROACTIVE     Risk decision applied                 MONITOR
 5 PASS  PAYMENT       Payment proceeds                      server-authorised amount forwarded
 6 PASS  REACTIVE      Transaction enters monitoring
 7 WARN  REACTIVE      Reactive monitoring                   3 patterns detected
 8 PASS  NETWORK       Graph engine rebuilds the network     32 candidate clusters
 9 WARN  NETWORK       GNN scores the network                11 suspicious; NET-0001 at 99.6
10 WARN  NETWORK       Alert created                         ALERT-E7D17BF3
11 PASS  INVESTIGATION Investigator opens the alert          NEW → UNDER_REVIEW (audited)
12 PASS  INVESTIGATION Reviews network and history           CASE-1011: 6 alerts, 25 txns
13 PASS  INVESTIGATION Adds a note                           audited; case remains open
```

`TAMPERED_AMOUNT` (3 steps) — correctly stops at the gate, with no AML scoring and nothing
forwarded.

---

## 11. AML language policy

The platform never asserts that anyone is a money launderer. Enforced in the code, not just
by convention — alert titles, network summaries and GNN signals are generated from templates
that use indicator language only:

> "High-risk transaction" · "Potentially suspicious activity" · "Requires investigation" ·
> "Potential laundering pattern" · "Model-generated risk assessment"

Every score, alert, network assessment and case file carries a standing advisory:

> A risk score is a prioritisation signal, not a finding of wrongdoing. It indicates that
> activity warrants human review under the institution's AML procedures. It does not
> establish that any offence occurred, and it must not be treated as evidence or
> communicated to the customer as an accusation.

Colour is never the only carrier of meaning: every risk band ships with its text label, and
severity indicators include an icon.

---

## 12. Known limitations

- **Mule archetype under-scores on the proactive layer.** Seeded mule accounts reach
  rapid-movement ratios of 0.47–0.56 against a 0.70 rule threshold, so they land in MEDIUM
  rather than HIGH on behavioural signals alone. The pipeline measures the signal correctly
  — the seed generator simply forwards ~50% of inbound value within the window rather than
  ~90%. These accounts *are* caught by the network layer (99.6/100) and by reactive alerts.
  Tuning the generator or lowering `RAPID_FUND_MOVEMENT` would close the gap.
- **Edge/subgraph GNN metrics saturate** — see §6.
- **No PyTorch Geometric.** The GNN is hand-written; the interface exists for a PyG swap
  but it is not implemented.
- **Reactive sweeps and network analysis are synchronous.** In production these belong on a
  task queue (Celery/RQ); a full-graph sweep over ~18k transactions takes a few seconds.
- **No rate limiting, token refresh, or token revocation list.** Tokens simply expire.
- **Dashboard aggregates are computed per request.** Real deployments would materialise
  them.

---

## 13. Verification performed

**Backend** — booted with uvicorn against the seeded database:

- Auth: valid login for both roles; wrong password → 401; unauthenticated read → 401.
- RBAC: analyst → `/api/audit-logs` → **403**; admin → **200**.
- All 12 page-backing endpoints (plus the two detail routes) return 200 with populated
  data: 18,132 transactions, 120 customers, 156 alerts, 32 networks, 10 investigations,
  20 rules.
- Integrity gateway: honest amount → `VERIFIED` / `ALLOW`, amount forwarded; tampered ×10 →
  `AMOUNT_MISMATCH` / `BLOCK`, **nothing forwarded, no transaction created, AML scoring
  skipped**.
- Risk-factor contributions confirmed to sum exactly to the displayed score (spot-checked
  across the three highest-risk customers).
- Both demo scenarios run end to end (13 steps and 3 steps respectively).
- Trained-model loading confirmed via `/api/health`: `proactive_rf` and `aml_gnn` both
  report `trained: true`.

**Frontend** — production build clean (2,832 modules, no warnings beyond chunk size), and
driven in a real browser:

- Login → dashboard: all 7 KPIs, 6 charts, pipeline strip, geo and channel breakdowns, and
  the top-alert queue render from live API data.
- GNN Network page: 11 flagged clusters listed, React Flow canvas mounts with nodes, edges,
  controls and the legend; GNN assessment panel shows 7 signals each backed by a measured
  quantity.
- Security Gateway: reproduced the specification's exact scenario in the UI — order
  `ORD-82341`, authorised ₹8,000, client claim ₹80,000 → `AMOUNT_MISMATCH`, mismatch
  ₹72,000 (900%), decision **BLOCK**, downstream AML steps `SKIPPED`.
- Model Insights: real metrics read from the artifacts, with the trained-artifact banner and
  limitations section.
- Reactive AML: 60 narrative pattern cards with their measurements.
- Console: zero errors on a clean page load.

Two defects were found and fixed during this pass: the network sweep failed to detach
`Investigation`/`RiskAssessment` foreign keys before regenerating clusters (FK violation on
re-run), and `NetworkGraph` called `useReactFlow()` without a `ReactFlowProvider`, which
crashed the graph page. A route-level error boundary was added so a single failing panel can
no longer blank the console.
