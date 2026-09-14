"""Rebuild docs/standalone-demo.html from the current policy, history and engine port.

Run after changing app/policy.json, data/transactions.csv or app/engine.py:

    python scripts/build_standalone_demo.py          # rebuild + parity check (needs node)
    python scripts/build_standalone_demo.py --no-check

Steps: 1) export policy + per-merchant profiles to JSON, 2) inject them and the JavaScript
engine port into the template, 3) if node is available, run the JS engine against the Python
engine on ~500 request fixtures and fail if any decision, amount, rate, term, reason or factor
differs. If you changed app/engine.py you must mirror the change in scripts/standalone/engine.js;
the parity check tells you if you forgot.
"""
from __future__ import annotations

import csv
import dataclasses
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.history import HistoryStore  # noqa: E402
from app.main import build_engine  # noqa: E402
from app.schemas import DecisionRequest  # noqa: E402

OUT = ROOT / "docs" / "standalone-demo.html"
TEMPLATE = ROOT / "scripts" / "standalone" / "template.html"
ENGINE_JS = ROOT / "scripts" / "standalone" / "engine.js"

VARIANTS = [
    dict(risk_tier="B", credit_limit=50000, current_exposure=30000, transaction_amount=12000, monthly_purchase_volume=65000, inventory_level={"a": 1, "b": 2, "c": 3}),
    dict(risk_tier="A", credit_limit=100000, current_exposure=80000, transaction_amount=35000, monthly_purchase_volume=220000, inventory_level={}),
    dict(risk_tier="C", credit_limit=20000, current_exposure=2000, transaction_amount=9000, monthly_purchase_volume=30000, inventory_level={"x": 5}),
    dict(risk_tier="D", credit_limit=30000, current_exposure=5000, transaction_amount=6000, monthly_purchase_volume=40000, inventory_level={}),
    dict(risk_tier="B", credit_limit=300000, current_exposure=0, transaction_amount=240000, monthly_purchase_volume=80000, inventory_level={}),
    dict(risk_tier="E", credit_limit=50000, current_exposure=0, transaction_amount=5000, monthly_purchase_volume=50000, inventory_level={}),
    dict(risk_tier="A", credit_limit=50000, current_exposure=49000, transaction_amount=12000, monthly_purchase_volume=65000, inventory_level={}),
    dict(risk_tier="B", credit_limit=50000, current_exposure=30000, transaction_amount=300, monthly_purchase_volume=65000, inventory_level={}),
]


def export_data() -> dict:
    store = HistoryStore.from_csv()
    meta = {r["merchant_id"]: r for r in csv.DictReader((ROOT / "data" / "merchants.csv").open())}
    profiles = {}
    for mid, m in meta.items():
        p = store.get(mid)
        d = dataclasses.asdict(p)
        d.update(settled_financed=p.settled_financed, on_time_rate=p.on_time_rate, segment=m["segment"], city=m["city"],
                 tier=m["risk_tier"], credit_limit=int(m["credit_limit_sar"]), archetype=m["archetype"])
        profiles[mid] = d
    return {"policy": json.loads((ROOT / "app" / "policy.json").read_text()), "as_of": store.as_of.isoformat(), "profiles": profiles}


def build(data: dict) -> str:
    engine = ENGINE_JS.read_text()
    engine = engine.replace("if (typeof module !== 'undefined') module.exports = { decide };", "")
    engine = engine.replace("function decide(req, profiles, policy)", "function decide_original(req, profiles, policy)")
    html = TEMPLATE.read_text().replace("__DATA__", json.dumps(data)).replace("__ENGINE__", engine.rstrip())
    OUT.write_text(html)
    return html


def fixtures(data: dict) -> list[dict]:
    engine = build_engine()
    out = []
    for mid in [*data["profiles"].keys(), ""]:
        for v in VARIANTS:
            req = DecisionRequest(merchant_id=mid, merchant_business_description="", **v)
            r = engine.decide(req).response
            out.append({"req": req.model_dump(), "out": {"decision": r.decision, "approved_amount": r.approved_amount, "interest_rate": r.interest_rate,
                        "repayment_terms": r.repayment_terms, "reason": r.reason, "score": r.score, "risk_band": r.risk_band,
                        "factors": [f.model_dump() for f in r.factors]}})
    return out


PARITY_JS = r"""
const { decide } = require(process.argv[2]); const data = require(process.argv[3]); const fixtures = require(process.argv[4]);
let bad = 0;
for (const fx of fixtures) {
  const out = decide(fx.req, data.profiles, data.policy), exp = fx.out;
  const diff = ['decision','approved_amount','interest_rate','repayment_terms','reason','score','risk_band'].filter(k => String(out[k]) !== String(exp[k]));
  const norm = fs => JSON.stringify(fs.map(f => [f.code, f.impact, f.description]));
  if (norm(out.factors) !== norm(exp.factors)) diff.push('factors');
  if (diff.length && ++bad <= 5) console.log('MISMATCH', fx.req.merchant_id || '(unknown)', fx.req.risk_tier, diff.join(','));
}
console.log(`${fixtures.length - bad}/${fixtures.length} fixtures match`); process.exit(bad ? 1 : 0);
"""


def parity_check(data: dict) -> bool:
    node = shutil.which("node")
    if not node:
        print("node not found: skipping parity check (install Node.js to enable it)")
        return True
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "data.json").write_text(json.dumps(data))
        (t / "fixtures.json").write_text(json.dumps(fixtures(data)))
        (t / "parity.js").write_text(PARITY_JS)
        res = subprocess.run([node, str(t / "parity.js"), str(ENGINE_JS), str(t / "data.json"), str(t / "fixtures.json")], text=True, capture_output=True)
        print(res.stdout.strip())
        if res.returncode:
            print(res.stderr.strip(), file=sys.stderr)
            return False
    return True


if __name__ == "__main__":
    d = export_data()
    html = build(d)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(html) // 1024} KB, policy {d['policy']['version']}, {len(d['profiles'])} merchants)")
    if "--no-check" not in sys.argv and not parity_check(d):
        sys.exit("standalone engine.js does not match app/engine.py — fix the port before shipping the demo")
