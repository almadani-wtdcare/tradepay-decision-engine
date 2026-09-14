# How the decision logic works — and how the transaction history is used

## 1. The synthetic history

`data/generate_history.py` builds a deterministic 12-month dataset (seeded, so anyone can
regenerate it byte-for-byte) for **60 merchants** in six behavioural archetypes:

| Archetype | IDs | Tier | Behaviour simulated |
|---|---|---|---|
| prime | M-1001–1012 | A | High volume, 2 % late, no defaults, flat growth |
| steady | M-1013–1030 | B | Mid volume, 8 % late, no defaults |
| growing | M-1031–1042 | B | Lower volume but +6 %/month growth, 10 % late |
| stretched | M-1043–1050 | C | 30 % late, 2 % default, shrinking volume |
| delinquent | M-1051–1056 | D | 45 % late, 15 % default, sharply shrinking |
| thin | M-1057–1060 | C | Only 2 months and 1–2 orders/month on file |

Each transaction has an amount, a date, whether it was financed, the term, days-to-repay and a
status (`cash`, `on_time`, `late`, `default`, `open`). About 70 % of orders are financed.

## 2. What we extract per merchant (`app/history.py`)

At startup every merchant is collapsed into a `MerchantProfile`:

* `on_time_rate` = on-time / (on-time + late + default) for settled financed orders
* `late_count`, `default_count`
* `average_amount`, `max_amount` (typical ticket size)
* `average_days_to_repay`
* `volume_trend` = last-90-day volume / prior-90-day volume
* `days_since_last_transaction`, `transactions_last_30d`

These are the "supply-chain behavioural signals" the case study talks about: purchase
frequency, invoice values, repayment discipline, growth.

## 3. Hard rules (policy gates)

| Code | Fires when |
|---|---|
| `TIER_NOT_ELIGIBLE` | tier not in `eligible_tiers` (E today) |
| `BELOW_MIN_TICKET` | amount < SAR 500 |
| `NO_AVAILABLE_CREDIT` | exposure ≥ limit |
| `PRIOR_DEFAULT` | defaults in history > `max_defaults` (0) |
| `FRAUD_AMOUNT_VS_VOLUME` | amount > 2× monthly purchase volume |
| `FRAUD_AMOUNT_VS_HISTORY` | amount > 5× merchant's historical average ticket |

Any hit ⇒ `DECLINED`, reason = the rule text, no pricing.

## 4. The score (0–100)

| Factor | Points | Rationale |
|---|---|---|
| `TIER_BASE` | A 80 · B 68 · C 56 · D 44 | Pre-scoring already encodes the long-run view |
| `REPAYMENT_DISCIPLINE` | (on-time rate − 85 %) × 100, clipped [−20, +12], **positive side weighted by confidence = min(1, settled orders / 10)** | 100 % across 2 orders proves little; across 50 it proves a lot |
| `LATE_PAYMENTS` | −3 per late order, floor −12 | |
| `VOLUME_GROWING` / `VOLUME_SHRINKING` | +4 / −6 | A shrinking business is the leading indicator of stress |
| `DORMANT` | −5 if no order in 60+ days | |
| `SHORT_HISTORY` | −4 if < 10 orders | |
| `THIN_FILE` | −8 if unknown merchant | Rely on tier only, cautiously |
| `OVER_LIMIT` / `HIGH_UTILISATION` / `LOW_UTILISATION` | −8 / −5 / +3 | Exposure after this order vs limit |
| `LARGE_VS_MONTHLY` / `SIZEABLE_VS_MONTHLY` / `ROUTINE_ORDER` | −10 / −4 / +2 | Order vs the merchant's normal monthly buying |
| `UNUSUALLY_LARGE` / `ABOVE_AVERAGE` | −8 / −4 | Order vs the merchant's own average ticket |
| `SKU_DIVERSITY` | +2 if ≥ 3 SKUs in inventory | Diversified stock, lower concentration risk |

Score = Σ factors, clipped to 0–100. Because it is a plain sum, the `factors` array in the
response is a complete, exact explanation.

## 5. Bands, sizing and pricing

| Band | Score | Approval cap | Fee adder |
|---|---|---|---|
| LOW | ≥ 70 | 100 % | +0.00 % |
| MEDIUM | 55–69 | 80 % | +0.25 % |
| ELEVATED | 45–54 | 50 % | +0.50 % |
| HIGH | < 45 | 0 % (decline) | – |

`approved = floor_100(min(request, available_credit, request × cap))`.
If `approved == request` → **APPROVED**. If `approved < max(SAR 500, 20 % of request)` →
**DECLINED** (a token partial would only frustrate the merchant). Otherwise
**PARTIALLY_APPROVED**, and the reason states whether *available credit* or the *risk band*
was the binding constraint.

Fee (flat, for the term): tier base (A 1.0 % · B 1.5 % · C 2.0 % · D 2.5 %) + band adder.
Term: tier default (A/B 30 d · C 21 d · D 14 d); LOW-band merchants with ≥ 10 settled orders and
≥ 95 % on-time get +15 days (max 45).

## 6. Worked examples (from `scripts/demo.sh`)

* **Brief example, unknown merchant, tier B, 12 000 of 20 000 available** → base 68 − 8 thin file
  + 2 SKU = 62 → MEDIUM → cap 9 600 → `PARTIALLY_APPROVED 9 600 @ 1.75 % / 30 days`.
* **M-1001 (prime), tier A, 25 000 order** → 80 + 12 discipline + 3 low utilisation
  + 2 routine order + 2 SKU = 99 → LOW → `APPROVED` in full @ 1.0 % / 45 days.
* **M-1005, order 35 000 with 20 000 available** → 80 + 12 − 8 over-limit = 84, LOW band but
  credit-bound → `PARTIALLY_APPROVED 20 000`, reason: "exceeds the remaining credit limit".
* **M-1052 (3 defaults)** → `PRIOR_DEFAULT` gate → `DECLINED` (score would be 11 anyway).
* **240 000 order on 80 000 monthly volume** → `FRAUD_AMOUNT_VS_VOLUME` → `DECLINED`.

## 7. Why not ML today, and what would change my mind

We have no *real* repayment outcomes yet; training a model on data we generated ourselves would
only teach it the rules we wrote. The right sequence is: ship the transparent policy, log every
feature vector and outcome, and after ~3 months of real repayments fit a logistic regression or
gradient-boosted model as a *challenger* that runs in shadow mode. The `Factor` interface already
supports SHAP-style per-feature contributions, so explainability survives the upgrade.
