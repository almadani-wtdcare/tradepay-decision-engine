from tests.conftest import make


def test_case_study_example_partial_on_thin_file(engine, base_request):
    r = engine.decide(make(base_request)).response
    assert r.decision == "PARTIALLY_APPROVED"
    assert 0 < r.approved_amount < 12000
    assert r.approved_amount % 100 == 0
    assert r.interest_rate > 0 and r.repayment_terms.endswith("days")
    assert "thin-file" in r.reason.lower() or "no transaction history" in r.reason.lower()


def test_full_approval_for_prime_merchant(engine, base_request):
    r = engine.decide(make(base_request, merchant_id="GOOD", risk_tier="A")).response
    assert r.decision == "APPROVED"
    assert r.approved_amount == 12000
    assert r.risk_band == "LOW"
    assert r.repayment_terms == "45 days"          # good-payer extension
    assert r.interest_rate == 1.0                  # tier A base, no adder


def test_partial_driven_by_available_credit(engine, base_request):
    # 20k available, 30k requested, strong merchant → approve what is available.
    r = engine.decide(make(base_request, merchant_id="GOOD", risk_tier="A", transaction_amount=30000,
                           monthly_purchase_volume=200000)).response
    assert r.decision == "PARTIALLY_APPROVED"
    assert r.approved_amount == 20000
    assert "exceeds the remaining credit limit" in r.reason


def test_decline_when_partial_would_be_too_small(engine, base_request):
    # Only 1,000 available for a 12,000 order (<20%) → not useful → decline.
    r = engine.decide(make(base_request, merchant_id="GOOD", current_exposure=49000)).response
    assert r.decision == "DECLINED"
    assert r.approved_amount == 0


def test_decline_for_prior_default(engine, base_request):
    r = engine.decide(make(base_request, merchant_id="BAD")).response
    assert r.decision == "DECLINED"
    assert any(f.code == "PRIOR_DEFAULT" for f in r.factors)
    assert r.interest_rate == 0 and r.repayment_terms == "n/a"


def test_decline_for_tier_e(engine, base_request):
    r = engine.decide(make(base_request, risk_tier="e")).response
    assert r.decision == "DECLINED"
    assert "tier E" in r.reason


def test_decline_for_low_score(engine, base_request):
    r = engine.decide(make(base_request, merchant_id="LATE", risk_tier="D", transaction_amount=19000,
                           monthly_purchase_volume=30000)).response
    assert r.decision == "DECLINED"
    assert r.risk_band == "HIGH"


def test_pricing_rises_with_tier_and_band(engine, base_request):
    tier_a = engine.decide(make(base_request, merchant_id="GOOD", risk_tier="A")).response
    tier_c = engine.decide(make(base_request, merchant_id="GOOD", risk_tier="C")).response
    assert tier_c.interest_rate > tier_a.interest_rate          # tier base rate
    low_band = engine.decide(make(base_request, merchant_id="GOOD", risk_tier="B")).response
    mid_band = engine.decide(make(base_request, merchant_id="", risk_tier="B")).response
    assert low_band.risk_band == "LOW" and mid_band.risk_band == "MEDIUM"
    assert mid_band.interest_rate > low_band.interest_rate      # band adder


def test_response_carries_audit_fields(engine, base_request):
    r = engine.decide(make(base_request, merchant_id="GOOD")).response
    assert r.decision_id and r.policy_version
    assert r.merchant_history.transactions == 18
    assert sum(f.impact for f in r.factors) == r.score or r.score in (0, 100)
    assert r.processing_time_ms < 50
