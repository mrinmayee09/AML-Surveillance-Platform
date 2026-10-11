# The reactive GNN, explained simply

A guide to the graph neural network part of the project: what it does, how it
was built step by step (R1–R6), and how to explain it in an interview or viva.
The measured numbers are in [GNN_RESULTS.md](GNN_RESULTS.md).

---

## 1. The idea in one paragraph

Money launderers rarely give themselves away in a single account. They move
money through **networks** of accounts: chains that pass money along, circles
that send it back to where it started, one account fanning money out to many.
You only see this by looking at **who paid whom** - a graph. So after a payment
settles, the platform looks at each account together with its neighbourhood of
counterparties and asks a **graph neural network (GNN)** how suspicious that
neighbourhood looks. The GNN is trained on **IBM AMLworld**, a public anti-money
laundering benchmark, and compared honestly against simpler models.

## 2. Where it sits in the platform

| Layer | Question | Method |
|---|---|---|
| 1. Integrity | Was the payment request tampered with? | Server-side amount check (rules) |
| 2. Proactive | Is this customer behaving riskily right now? | Rules + Random Forest, before payment |
| **3. Reactive** | **Are accounts working together to launder money?** | **Graph + GraphSAGE GNN, after payment** |

## 3. How the reactive GNN works (the pipeline)

```
settled payment
   │
   ▼
build a "window" around each account involved     (R1)
   7 days of history, up to 3 hops of counterparties, at most 300 accounts
   │
   ▼
GraphSAGE scores the account                      (R2, R3)
   each account combines its own numbers with its neighbours', 3 times
   │
   ▼
explain the score                                 (R4)
   which transfers made the score high?
   │
   ▼
alert for the analyst, shown on the Network page  (R5)
```

### What is a "window"?
A small map around one account: the accounts it paid, the accounts that paid
it, their counterparties, and so on up to 3 steps away, using the last 7 days
of settled transfers. Every account in the map is described by simple numbers:
money in, money out, how many counterparties, how quickly it passes money on
after receiving it, how much crosses borders or banks, and so on.

### What is GraphSAGE?
GraphSAGE (Hamilton et al., 2017) is a GNN that works in three steps per layer:

1. **Gather** - look at your neighbours' current numbers and average them.
2. **Combine** - mix that average with your own numbers.
3. **Repeat** - after 3 layers, each account has "heard" from accounts up to
   3 steps away.

A mule account in the middle of a laundering chain ends up "knowing" it sits
between a sender and a fast forwarder, because that information flowed to it.
GraphSAGE learns a **rule**, not one answer per account, so it can score
**accounts it has never seen** - essential for a payment app that opens new
accounts every day.

### Our three versions (the R3 ablation)

| Version | What it adds | Why |
|---|---|---|
| **A. Plain GraphSAGE** | Neighbours pooled together, direction ignored | The textbook model |
| **B. Directed GraphSAGE** | "Who paid me" and "who I paid" handled separately, weighted by amount | In money, direction matters: collectors receive from many, distributors send to many |
| **C. Edge-aware directed GraphSAGE** | Each message also carries the transfer's details (amount, how soon after a receipt it was sent, payment type, cross-bank) | A fast relay through a fresh account should look different from an ordinary payment |

Adding **one idea at a time** and measuring each is called an *ablation study*.

## 4. What was built, step by step

### R1 - Windows and features
- Built the window builder (`app/graph/window.py`) and the feature definitions
  (`app/graph/features_v2.py`).
- Key fix: an account's numbers are computed from **all** its activity, so it
  looks the same in every window it appears in. (The old version recomputed
  them per sub-graph, so the same account could get different scores.)
- The same code builds windows from the database (live) and from the dataset
  (training) - training and live data cannot drift apart.

### R2 - A real benchmark and a fair comparison
- **Dataset:** IBM AMLworld HI-Small (5 million transfers, labelled laundering).
- **Split by time:** train on the first days, choose settings on the next days,
  test on the last days - like real life, where you predict the future.
- **Data trap removed:** after 10 Sept the dataset is ~59% laundering (the
  simulator kept laundering after normal activity stopped). Left in, it would
  have made every model look excellent. We cut it off and say so.
- **Fair comparison:** the GNN against gradient boosting and logistic regression
  that get the same information *without* learning on the graph.
- **Honest scoring:** only ~0.3% of active accounts launder on a given day, so
  accuracy is meaningless (flag nobody → 99.7% accurate). We report precision,
  recall and PR-AUC.

### R3 - GraphSAGE ablation
Trained versions A, B and C on exactly the same windows, seeds and rules. The
model the app uses is the version with the best **validation** score; the test
set never influences that choice.

### R4 - Explanations
For a flagged account, remove each nearby transfer in turn and re-score. The
transfers whose removal lowers the score most are "why it was flagged". We
also **test** the explanations: removing the top transfers should lower the
score far more than removing random ones.

### R5 - Connected to the app
- The trained model is saved once; the app only loads it.
- When a payment settles, both accounts are scored in the background (it never
  slows the payment). Analysts can also click **Run GNN scoring** on the
  Network page.
- A score above the model's threshold creates an alert (no duplicates). The
  alert and the Network page show the score, the threshold and the transfers
  behind it.

### R6 - Results and write-up
- `docs/GNN_RESULTS.md` - every table generated from the run reports
  (`python -m app.gnn.report_md`).
- This guide.

## 5. What we found (headline results)

Test split, 5 seeds, mean ± std. Only ~0.33% of active accounts launder on a
given day, so a random guess scores PR-AUC ≈ 0.003. Full tables:
[GNN_RESULTS.md](GNN_RESULTS.md).

| Model | Test PR-AUC | Precision | Recall |
|---|---|---|---|
| Gradient boosting, account's own features | 0.049 ± 0.001 | 0.075 | 0.144 |
| Gradient boosting, + hand-made neighbour features | 0.137 ± 0.021 | 0.147 | 0.242 |
| A. Plain GraphSAGE | 0.029 ± 0.008 | 0.042 | 0.214 |
| B. Directed GraphSAGE | 0.042 ± 0.009 | 0.045 | 0.158 |
| **C. Edge-aware directed GraphSAGE** | **0.183 ± 0.024** | **0.224** | **0.252** |

What this means, in plain words:
1. **Direction helps** (A → B): treating "who paid me" and "who I paid"
   separately beats pooling them.
2. **Transfer details are the big step** (B → C, more than 4×): a GNN that only
   knows *who* is connected is worse than gradient boosting with good hand-made
   features. Once each message also carries *how* the money moved (amount,
   timing after a receipt, payment type, cross-bank), the GNN beats the best
   baseline - on every pattern except fan-in and stack, where it is level.
3. **Explanations are faithful** (R4): removing the 3 transfers an explanation
   names drops a flagged account's score by 0.45 on average, versus 0.04 for 3
   random nearby transfers, and un-flags 70% of accounts (17% for random).

One honest caveat for the viva: a 0.18 PR-AUC means about 1 in 4-5 alerts is a
true laundering account at ~25% recall. That is far better than chance (0.003)
and than the baselines, and in line with how hard AMLworld is - but it is a
prioritisation aid for analysts, not an automatic verdict.

## 6. Paper text (ready to adapt)

**Dataset.** Because labelled real-world transaction data is not publicly
available - privacy regulation and the confidentiality of suspicious-transaction
reports prevent it - we evaluate the network layer on IBM AMLworld HI-Small
(Altman et al., 2023), a widely used simulated benchmark of 5.08 million
transfers between 515,088 accounts. After 10 September 2022 the simulator emits
only 1,108 transfers, 59% of them laundering; we exclude these days because a
time-ordered test split containing them would reward mere activity detection.

**Protocol.** Transfers are split by time (60/20/20 by count, aligned to UTC
days). For each account active on a day we build its 7-day, 3-hop neighbourhood
(at most 300 accounts) and predict whether it took part in a laundering transfer
that day. All positive accounts are kept; negatives are sampled (1% train, 2%
validation/test) and re-weighted, so precision and PR-AUC estimate performance on
all active accounts (base rate 0.33%). Thresholds and model selection use the
validation split only; each model is trained with 5 seeds.

**Models.** We compare gradient boosting and logistic regression on the
account's features and on hand-crafted neighbour and transfer aggregates with
three GraphSAGE variants: (A) the standard undirected mean aggregator,
(B) separate inbound/outbound aggregation weighted by amount, and (C) B with
messages computed from both the neighbour state and the transfer's features
(amount, relay latency, payment rail, cross-institution flag).

**Results.** Direction-aware aggregation improves on the undirected model
(PR-AUC 0.042 vs 0.029), but without transfer features both GraphSAGE variants
trail gradient boosting on hand-crafted neighbourhood features (0.137). The
edge-aware variant reaches 0.183 ± 0.024 (precision 0.224, recall 0.252),
outperforming all baselines and recalling more of the cycle, fan-out and
scatter-gather typologies. Occlusion explanations are faithful: deleting the
three highest-attributed transfers lowers a flagged account's score by 0.45 on
average versus 0.04 for three random neighbouring transfers.

**Limitations.** AMLworld is simulated and has no customer profile data; the
platform's INR/UPI demonstration data differs in currency and payment rails,
so measured accuracy refers to AMLworld only. Explanations remove a transfer from
message passing but not from the account's window statistics.


## 7. Five-minute demo script

1. **Dashboard** (30 s) - three layers: integrity, proactive, reactive.
2. **Security Gateway** (60 s) - tamper with an amount → blocked; normal payment → allowed.
3. **Network page** (90 s) - click **Run GNN scoring**; open a flagged account;
   show the GraphSAGE score, the threshold and "score rests mainly on these
   transfers".
4. **Alert detail** (60 s) - the GNN alert with its explanation and the
   AMLworld disclaimer; take it for review.
5. **Results** (60 s) - one table from `GNN_RESULTS.md`: GNN versions vs
   gradient boosting, and the explanation-fidelity check.

## 8. Commands

```bash
cd backend
# R2: baselines + directed GraphSAGE (5 seeds); builds and caches the windows
python -m app.gnn.r2 --trans ../data/amlworld/HI-Small_Trans.csv --patterns ../data/amlworld/HI-Small_Patterns.txt --until 2022-09-10
# R3: GraphSAGE ablation; exports the selected model to app/gnn/artifacts/aml_gnn_v2.pt
python -m app.gnn.r3 --trans ../data/amlworld/HI-Small_Trans.csv --patterns ../data/amlworld/HI-Small_Patterns.txt --until 2022-09-10
# R4: explanation fidelity
python -m app.gnn.r4 --trans ../data/amlworld/HI-Small_Trans.csv --patterns ../data/amlworld/HI-Small_Patterns.txt --until 2022-09-10
# R6: regenerate docs/GNN_RESULTS.md
python -m app.gnn.report_md
```
