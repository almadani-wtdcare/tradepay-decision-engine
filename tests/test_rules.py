from app.engine import build_features, evaluate_hard_rules
from tests.conftest import make


def codes(f, policy):
    return {h.code for h in evaluate_hard_rules(f, policy)}


def test_tier_e_is_not_eligible(base_request, policy, history):
    f = build_features(make(base_request, risk_tier="E"), None)
    assert "TIER_NOT_ELIGIBLE" in codes(f, policy)


def test_no_available_credit(base_request, policy):
    f = build_features(make(base_request, current_exposure=50000), None)
    assert "NO_AVAILABLE_CREDIT" in codes(f, policy)


def test_below_min_ticket(base_request, policy):
    f = build_features(make(base_request, transaction_amount=200), None)
    assert "BELOW_MIN_TICKET" in codes(f, policy)


def test_prior_default_blocks(base_request, policy, history):
    f = build_features(make(base_request, merchant_id="BAD"), history.get("BAD"))
    assert "PRIOR_DEFAULT" in codes(f, policy)


def test_fraud_amount_vs_monthly_volume(base_request, policy):
    f = build_features(make(base_request, transaction_amount=140_000, credit_limit=200_000, current_exposure=0), None)
    assert "FRAUD_AMOUNT_VS_VOLUME" in codes(f, policy)


def test_fraud_amount_vs_history(base_request, policy, history):
    # GOOD averages 10k; 60k is 6x the historical ticket.
    f = build_features(make(base_request, merchant_id="GOOD", transaction_amount=60_000, credit_limit=200_000,
                            current_exposure=0, monthly_purchase_volume=200_000), history.get("GOOD"))
    assert "FRAUD_AMOUNT_VS_HISTORY" in codes(f, policy)


def test_clean_request_has_no_hits(base_request, policy, history):
    f = build_features(make(base_request, merchant_id="GOOD"), history.get("GOOD"))
    assert codes(f, policy) == set()
