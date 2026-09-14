# Demo walkthrough (≈ 6 minutes)

## Before the demo
```bash
docker compose up --build        # terminal 1 — keep visible: each decision prints a JSON audit line
```
Open http://localhost:8080/demo in a browser. (Swagger UI is at /docs if anyone wants the raw API.)

Backup if Docker misbehaves: double-click `docs/standalone-demo.html`. Same scenarios, same decisions, runs entirely in the browser.

## Act 1 — health and history (30 s)
Open http://localhost:8080/health → policy version, 60 merchants of pre-aggregated history.
*"Features are pre-aggregated at startup, so a decision is a dictionary lookup plus arithmetic."*

## Act 2 — seven scenarios on the demo page (4 min)
| Preset | Outcome | Point to make |
|---|---|---|
| Brief example · unknown merchant | PARTIALLY_APPROVED 9,600 / 12,000 | Thin-file penalty → MEDIUM band caps at 80 %. The score is literally the sum of the bars. |
| Prime merchant · M-1001 | APPROVED, 45 days | 12 months of perfect repayment earns the good-payer term extension. |
| Order above remaining credit · M-1005 | PARTIALLY_APPROVED 20,000 | Strong merchant, credit-bound. The reason says which constraint bound. |
| Late payer · M-1020 | PARTIALLY_APPROVED | Six late repayments cost 12 points; still financeable, at a higher fee. |
| Prior default · M-1052 | DECLINED (rule) | Hard rules run before the score; a good score can never override a default. |
| Fraud gate · 3× monthly volume | DECLINED (two rules) | Fraud checks live in the same path, not a separate system. |
| Thin file · M-1058 | PARTIALLY_APPROVED | 100 % on-time across 2 orders earns almost nothing: history credit is confidence-weighted. |

After each click glance at terminal 1: *"That line is the audit record — inputs, factors, policy version, decision id."*
Edit any field live (e.g. raise `current_exposure` to the limit) to show the engine re-deciding.

## Act 3 — engineered, not scripted (1 min)
```bash
docker compose --profile test run --rm tests     # 38 tests
```
Open `app/policy.json`: *"Every threshold a credit officer would tune is here, versioned; every response carries the version."*

## Likely questions
* **Why not ML?** No real repayment outcomes yet; training on our own synthetic data teaches the model our rules. Ship the transparent policy, log every feature vector, train a shadow challenger on real outcomes.
* **Why a flat fee, not interest?** Maps to Sharia-compliant murabaha-style structures; simpler for a shopkeeper.
* **What breaks at 1M tx/day?** Not the engine (≈12 tx/s average). Pressure moves to ingestion and the feature store, which scale independently.
