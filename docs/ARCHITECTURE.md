# Architecture & Design Decisions

## 1. What this service is

A stateless HTTP microservice that turns a purchase transaction into a credit decision in
real time. It sits behind the partner-facing API gateway in the TradePay platform: the partner
(distributor / marketplace / SFA) posts the order, the gateway enriches it with the merchant's
pre-scored tier, limit and exposure, and calls `POST /decision`. The response is returned to the
point of sale synchronously, so the whole path must stay well inside 100 ms.

```
Partner order ─► API gateway ─► POST /decision ─► DecisionEngine ─► response + audit log
                                   │                  │
                                   │                  ├─ HistoryStore   (pre-aggregated merchant profiles, in memory)
                                   │                  └─ Policy         (versioned policy.json)
                                   └─ Pydantic validation (422 on bad input)
```

## 2. Request flow inside the engine (`app/engine.py`)

1. **Features** – combine the request with the merchant's historical profile into one flat
   `Features` object (available credit, utilisation after the order, order size relative to
   monthly volume and to the merchant's own average ticket, inventory breadth, repayment
   statistics, volume trend, recency).
2. **Hard rules** – policy gates that decline regardless of score: ineligible tier, no
   available credit, below minimum ticket, prior default, and two fraud/anomaly gates
   (order ≫ monthly volume, order ≫ merchant's historical ticket).
3. **Score** – an additive 0–100 risk score. The pre-scoring tier sets the base; each
   behavioural signal adds or removes a bounded number of points and is recorded as a named
   `Factor`. The score is literally the sum of the factors, so the explanation *is* the model.
4. **Sizing** – the score maps to a band (LOW / MEDIUM / ELEVATED / HIGH). Each band has an
   approval cap (100 % / 80 % / 50 % / 0 % of the request). Approved amount =
   `min(request, available credit, cap)` rounded down to SAR 100. A partial that is too small to
   be useful (< 20 % of the order or < SAR 500) becomes a decline instead of a token approval.
5. **Pricing** – flat fee = tier base rate + band adder; term = tier term, extended for proven
   good payers in the LOW band.
6. **Explanation** – a one-paragraph `reason` built from the decisive driver (rule hit,
   available-credit constraint, or top negative factors), plus the full factor list.
7. **Audit log** – one JSON line with everything above (`app/logging_utils.py`).

## 3. Key design decisions

| Decision | Choice | Why (and what we gave up) |
|---|---|---|
| Model type | Rules + additive score, not ML | The brief asks for explainability, auditability and a 4–6 h budget. An additive score gives per-decision attribution for free, is trivially unit-testable, and can be tuned by a credit officer without a data scientist. We give up the lift a gradient-boosted model would provide once real repayment outcomes exist; the feature vector we log today is exactly the training set for that model tomorrow. |
| Policy as data | `policy.json`, versioned | Limits, bands, rates and fraud thresholds change more often than code. Every response and log line carries `policy_version` so a decision can be reproduced against the policy that produced it. |
| History access | Pre-aggregated in memory at startup | The hot path is a dict lookup (µs). In production this becomes a feature store (Redis / DynamoDB) populated by the ingestion pipeline; the `HistoryStore` interface stays the same. |
| Hard rules before score | Two-stage | Regulatory and fraud gates must be un-overridable by a good score. Keeping them separate makes the policy readable and the tests obvious. |
| Partial approvals | Two independent constraints | Partial can be *credit-driven* (order > available limit → approve the available amount, the brief's example) or *risk-driven* (band cap). The `reason` tells the merchant which one applied. |
| Contract | Superset of the brief | The five required fields are present verbatim; `score`, `risk_band`, `factors`, `decision_id`, `policy_version`, `merchant_history`, `processing_time_ms` support ops dashboards and regulator queries. |
| Framework | FastAPI + Pydantic v2 | Type-validated contract, OpenAPI for free, async-ready, single-process cold start < 1 s. |
| Container | Multi-stage Dockerfile | `runtime` target ships only the app and the data; `test` target fails the build if a test fails; non-root user. |

## 4. Performance & availability (how this reaches 100 ms at 1M tx/day)

* 1M transactions/day ≈ 12 tx/s average, ~100 tx/s peak. A single uvicorn worker handles the
  engine in ~0.1 ms; the budget is dominated by network + feature fetch.
* Horizontal scaling is trivial because the service is stateless: run N replicas behind the
  gateway; features live in a shared low-latency store with a local LRU cache.
* Degradation path: if the feature store is unavailable, the engine already handles
  `profile=None` (thin-file mode) and can be configured to decline or approve conservatively.
* Idempotency: the gateway should pass an `Idempotency-Key`; the decision log keyed by
  `decision_id` + partner order id lets retries return the original decision.

## 5. Security & compliance notes

* No PII beyond `merchant_id` and a free-text description is accepted; the description is
  never used in scoring today (see improvements) so it cannot introduce bias.
* All decisions are logged with inputs, factors and policy version: this is the SAMA-facing
  audit trail and the merchant-facing "why was I declined" record.
* Deploy in-Kingdom (data residency) with TLS at the gateway, mTLS between services, secrets
  from a vault; none of this is in the exercise scope but the service has no state that would
  make it hard.

## 6. Testing strategy

* `tests/test_history.py` – aggregation of history into profiles (hand-built rows + real dataset).
* `tests/test_rules.py` – every hard rule fires on the right input and stays quiet on clean input.
* `tests/test_scoring.py` – base score by tier, direction of every factor, confidence weighting,
  score = sum of factors.
* `tests/test_engine.py` – end-to-end scenarios: brief example, full approval, credit-driven
  partial, too-small partial → decline, prior default, tier E, low score, pricing monotonicity,
  audit fields.
* `tests/test_api.py` – HTTP contract, validation (422s), history usage, JSON log emission.
