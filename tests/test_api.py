import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["merchants_in_history"] == 60


def test_decision_contract(client, base_request):
    res = client.post("/decision", json=base_request)
    assert res.status_code == 200
    body = res.json()
    assert body["decision"] in {"APPROVED", "PARTIALLY_APPROVED", "DECLINED"}
    for key in ("approved_amount", "interest_rate", "repayment_terms", "reason"):
        assert key in body


def test_known_merchant_uses_history(client, base_request):
    body = client.post("/decision", json={**base_request, "merchant_id": "M-1001", "risk_tier": "A"}).json()
    assert body["merchant_history"]["transactions"] > 0
    assert body["decision"] == "APPROVED"


def test_validation_errors(client, base_request):
    assert client.post("/decision", json={**base_request, "risk_tier": "Z"}).status_code == 422
    assert client.post("/decision", json={**base_request, "transaction_amount": -5}).status_code == 422
    assert client.post("/decision", json={**base_request, "inventory_level": {"sku": -1}}).status_code == 422
    assert client.post("/decision", json={}).status_code == 422


def test_decision_is_logged_as_json(client, base_request, capfd):
    client.post("/decision", json=base_request)
    out = capfd.readouterr().out
    line = next(l for l in out.splitlines() if '"tradepay.decision"' in l)
    record = json.loads(line)
    assert record["decision"]["outcome"]["decision"] in {"APPROVED", "PARTIALLY_APPROVED", "DECLINED"}
    assert record["decision"]["factors"]


def test_demo_page_is_served(client):
    res = client.get("/demo")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "POST /decision" in res.text
    assert client.get("/", follow_redirects=False).status_code == 307
