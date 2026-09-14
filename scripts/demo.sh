#!/usr/bin/env bash
# Fire a few representative requests at a running service (default http://localhost:8080).
set -euo pipefail
BASE="${1:-http://localhost:8080}"
post() { echo; echo "### $1"; shift; curl -s -X POST "$BASE/decision" -H 'content-type: application/json' -d "$1" | python3 -m json.tool; }

post "Case-study example (unknown merchant, thin file)" '{"merchant_id":"","merchant_business_description":"A small grocery store in a residential area of Riyadh, operating for 5 years.","risk_tier":"B","credit_limit":50000,"current_exposure":30000,"transaction_amount":12000,"monthly_purchase_volume":65000,"inventory_level":{"sku_A":100,"sku_B":50,"sku_C":200}}'
post "Prime merchant with 12 months of perfect repayment" '{"merchant_id":"M-1001","risk_tier":"A","credit_limit":116000,"current_exposure":20000,"transaction_amount":25000,"monthly_purchase_volume":250000,"inventory_level":{"sku_A":100,"sku_B":50,"sku_C":200}}'
post "Strong merchant, order larger than remaining credit" '{"merchant_id":"M-1005","risk_tier":"A","credit_limit":100000,"current_exposure":80000,"transaction_amount":35000,"monthly_purchase_volume":220000,"inventory_level":{}}'
post "Merchant with a prior default" '{"merchant_id":"M-1052","risk_tier":"D","credit_limit":30000,"current_exposure":5000,"transaction_amount":6000,"monthly_purchase_volume":40000,"inventory_level":{}}'
post "Anomalous order 3x monthly volume (fraud gate)" '{"merchant_id":"M-1020","risk_tier":"B","credit_limit":300000,"current_exposure":0,"transaction_amount":240000,"monthly_purchase_volume":80000,"inventory_level":{}}'
