# TradePay Decision Engine (Part 2 – Technical Deep Dive)

A decision-support microservice that evaluates a merchant purchase transaction in real time and
returns **APPROVED / PARTIALLY_APPROVED / DECLINED** with an approved amount, a financing fee,
repayment terms, and a human-readable reason. Every decision is fully explainable and logged as an
audit record.

| | |
|---|---|
| Stack | Python 3.12 · FastAPI · Pydantic v2 · pytest (38 tests) |
| Endpoint | `POST /decision` (plus `GET /health`, OpenAPI docs at `/docs`) |
| Decision logic | Transparent **hard-rules + additive risk score**, driven by a versioned `policy.json` and by 12 months of (synthetic) merchant transaction history |
| Latency | ~0.1 ms of engine time per decision (in-memory pre-aggregated features) |
| Docs | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`docs/DECISION_LOGIC.md`](docs/DECISION_LOGIC.md) · [`docs/IMPROVEMENTS.md`](docs/IMPROVEMENTS.md) · [`docs/DEMO.md`](docs/DEMO.md) |

## Run with Docker (recommended)

```bash
docker compose up --build            # API on http://localhost:8080
                                     # demo UI:  http://localhost:8080/demo   ·   OpenAPI docs: http://localhost:8080/docs
docker compose --profile test run --rm tests    # run the unit tests inside a container
```

Or with plain Docker:

```bash
docker build --target runtime -t tradepay/decision-engine .
docker run --rm -p 8080:8080 tradepay/decision-engine
docker build --target test .         # builds an image that runs the test suite (fails the build on red)
```

## Run locally without Docker

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -v                  # 38 tests
uvicorn app.main:app --reload --port 8080
```

## Demo

Open **http://localhost:8080/demo** for an interactive page: click one of seven preset scenarios
(the brief's example, a prime merchant, an order above remaining credit, a late payer, a prior
defaulter, a fraud-gate anomaly, a thin file) or edit any field, press **Decide**, and see the
decision, terms, the reason, the merchant's history summary and every scoring factor as a bar.
Each click also writes a JSON audit line to the server log.

No Docker handy? Open [`docs/standalone-demo.html`](docs/standalone-demo.html) directly in a browser.
It is the same engine ported to JavaScript with the policy and the 60-merchant history embedded,
verified to return identical decisions to the Python service on 488 request fixtures.
It is a generated file: after changing the policy, the data or the engine, run
`python scripts/build_standalone_demo.py` (rebuilds the page and re-runs the parity check; needs Node.js).

## Try it from the command line

```bash
curl -s -X POST http://localhost:8080/decision -H 'content-type: application/json' -d '{
  "merchant_id": "",
  "merchant_business_description": "A small grocery store in a residential area of Riyadh, operating for 5 years.",
  "risk_tier": "B",
  "credit_limit": 50000,
  "current_exposure": 30000,
  "transaction_amount": 12000,
  "monthly_purchase_volume": 65000,
  "inventory_level": {"sku_A": 100, "sku_B": 50, "sku_C": 200}
}'
```

```json
{
  "decision": "PARTIALLY_APPROVED",
  "approved_amount": 9600.0,
  "interest_rate": 1.75,
  "repayment_terms": "30 days",
  "reason": "Risk score 62 (MEDIUM) caps financing at 80% of the request. Approved SAR 9,600 of SAR 12,000. Drivers: No transaction history on file; applying thin-file penalty.",
  "decision_id": "…",
  "score": 62,
  "risk_band": "MEDIUM",
  "available_credit": 20000.0,
  "factors": [
    {"code": "TIER_BASE", "description": "Base score for pre-scoring tier B.", "impact": 68.0},
    {"code": "THIN_FILE", "description": "No transaction history on file; applying thin-file penalty.", "impact": -8.0},
    {"code": "SKU_DIVERSITY", "description": "Inventory spans 3 SKUs; diversified stock lowers concentration risk.", "impact": 2.0}
  ],
  "policy_version": "2026.09-v1",
  "merchant_history": null,
  "processing_time_ms": 0.14
}
```

The first five fields are the contract from the brief; the rest are explainability and audit
extras. `interest_rate` is a flat financing fee in **%** for the stated repayment term (1.75 % on
SAR 9,600 for 30 days).

`./scripts/demo.sh` fires five representative requests (thin file, prime merchant, order above
remaining credit, prior defaulter, fraud-gate anomaly) at a running instance.

Known merchants in the synthetic history are `M-1001` … `M-1060` (see `data/merchants.csv`);
e.g. `M-1001` is a prime payer, `M-1052` has defaults, `M-1058` has almost no history.

## Repository layout

```
app/
  main.py           FastAPI app: /decision, /health, /demo
  static/demo.html  interactive demo page (no build step, no dependencies)
  schemas.py        Pydantic request/response contracts
  engine.py         features → hard rules → score → sizing → pricing → explanation
  policy.py/.json   versioned credit policy (all tunables live in JSON, not code)
  history.py        loads transaction history, pre-aggregates a profile per merchant
  logging_utils.py  JSON-lines decision log (the audit trail)
data/
  generate_history.py   deterministic synthetic data generator (6 merchant archetypes)
  merchants.csv, transactions.csv   60 merchants, ~4,000 transactions, 12 months
scripts/            demo.sh (curl scenarios) · build_standalone_demo.py + standalone/ (engine port, template)
tests/              38 unit/API tests
docs/               architecture, decision logic, improvements, demo script, standalone browser demo
```

## Decision logging

Every call writes one JSON line to stdout (`logger = tradepay.decision`) containing the full
request, the merchant's history summary, every rule hit, every scoring factor with its point
contribution, the outcome and the latency. Ship it unchanged to an append-only store and you have
the regulator-facing audit trail. Set `LOG_LEVEL=DEBUG|INFO|WARNING`.
