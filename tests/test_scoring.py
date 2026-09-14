import pytest

from app.engine import build_features, compute_score
from tests.conftest import make


@pytest.mark.parametrize("tier,expected_base", [("A", 80), ("B", 68), ("C", 56), ("D", 44)])
def test_tier_sets_base_score(base_request, policy, tier, expected_base):
    _, factors = compute_score(build_features(make(base_request, risk_tier=tier), None), policy)
    assert next(f for f in factors if f.code == "TIER_BASE").impact == expected_base


def test_thin_file_is_penalised(base_request, policy):
    score, factors = compute_score(build_features(make(base_request), None), policy)
    assert any(f.code == "THIN_FILE" and f.impact < 0 for f in factors)


def test_good_history_beats_no_history(base_request, policy, history):
    no_hist, _ = compute_score(build_features(make(base_request), None), policy)
    good, factors = compute_score(build_features(make(base_request, merchant_id="GOOD"), history.get("GOOD")), policy)
    assert good > no_hist
    assert any(f.code == "REPAYMENT_DISCIPLINE" and f.impact > 0 for f in factors)


def test_late_payer_scores_below_good_payer(base_request, policy, history):
    good, _ = compute_score(build_features(make(base_request, merchant_id="GOOD"), history.get("GOOD")), policy)
    late, factors = compute_score(build_features(make(base_request, merchant_id="LATE"), history.get("LATE")), policy)
    assert late < good
    assert any(f.code == "LATE_PAYMENTS" for f in factors)


def test_tiny_history_gets_little_credit(base_request, policy, history):
    _, factors = compute_score(build_features(make(base_request, merchant_id="THIN"), history.get("THIN")), policy)
    discipline = next((f for f in factors if f.code == "REPAYMENT_DISCIPLINE"), None)
    # 100% on time across 1 order → confidence 1/10 → +1.2 at most
    assert discipline is None or discipline.impact <= 1.5
    assert any(f.code == "SHORT_HISTORY" for f in factors)


def test_utilisation_and_size_penalties(base_request, policy):
    tight = build_features(make(base_request, transaction_amount=19_000, monthly_purchase_volume=30_000), None)
    loose = build_features(make(base_request, transaction_amount=5_000, current_exposure=10_000), None)
    tight_score, tf = compute_score(tight, policy)
    loose_score, _ = compute_score(loose, policy)
    assert tight_score < loose_score
    assert {"HIGH_UTILISATION", "LARGE_VS_MONTHLY"} <= {f.code for f in tf}


def test_score_is_sum_of_factors_and_bounded(base_request, policy, history):
    score, factors = compute_score(build_features(make(base_request, merchant_id="LATE"), history.get("LATE")), policy)
    assert score == round(max(0, min(100, sum(f.impact for f in factors))))
