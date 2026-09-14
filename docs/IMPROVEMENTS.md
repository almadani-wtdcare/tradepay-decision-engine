# Optional improvements (given more time)

Ordered roughly by value ÷ effort.

## Decision quality
1. **Shadow-mode challenger model** — logistic regression / LightGBM trained on real repayment
   outcomes; serve rules as champion, log both, promote on measured lift (AUC, bad-rate at
   approval rate).
2. **Merchant-level dynamic limits** — recompute `credit_limit` nightly from volume trend and
   repayment behaviour instead of accepting it as input.
3. **Inventory-aware sizing** — use `inventory_level` × SKU velocity (from partner order lines)
   to estimate days-of-stock and flag overstocking or channel-stuffing.
4. **Velocity & duplicate checks** — orders per hour/day per merchant, identical-amount repeats,
   new-device / new-partner combos (needs timestamps and order ids in the request).
5. **Business-description NLP** — a small classifier (or an LLM with a fixed rubric) to derive
   segment / tenure features from `merchant_business_description`, gated behind fairness review
   so free text cannot introduce bias.
6. **Seasonality** — Ramadan / back-to-school uplift factors so a legitimately large order is not
   penalised as anomalous.

## Platform & operations
7. **Feature store** (Redis / DynamoDB, in-Kingdom) replacing the in-memory CSV, with a streaming
   updater from partner webhooks and a nightly batch reconciliation.
8. **Policy service** — hot-reload `policy.json` from a config store with approval workflow,
   diff view, and A/B allocation by merchant hash; keep `policy_version` on every decision.
9. **Idempotency & replay** — `Idempotency-Key` header, decision store keyed by partner order id,
   `GET /decision/{id}` for support and regulators.
10. **Observability** — Prometheus metrics (decision mix, approval rate, p50/p99 latency,
    factor frequency), OpenTelemetry traces, alert on approval-rate drift.
11. **Async audit sink** — ship JSON logs to Kafka → object storage → warehouse; retention and
    access policies aligned to SAMA.
12. **Resilience** — timeouts and circuit breaker on the feature store, explicit thin-file
    fallback policy, load tests (k6) at 100–500 rps.

## Engineering hygiene
13. CI pipeline (lint + type-check + tests + Docker build), pre-commit hooks, dependency scanning.
14. Property-based tests (Hypothesis) for the sizing function invariants
    (0 ≤ approved ≤ min(request, available), rounding, monotonic in score).
15. OpenAPI-generated client SDKs for partners; versioned `/v1/decision`.
16. Model/policy cards documenting intended use, factors, known limitations, fairness checks.
