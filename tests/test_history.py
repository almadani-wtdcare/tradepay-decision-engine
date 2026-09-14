from app.history import HistoryStore


def test_profiles_are_aggregated_per_merchant(history: HistoryStore):
    good = history.get("GOOD")
    assert good is not None
    assert good.transactions == 18
    assert good.on_time_rate == 1.0
    assert good.default_count == 0
    assert good.average_amount == 10_000


def test_late_and_default_counts(history: HistoryStore):
    late = history.get("LATE")
    assert late.late_count == 6
    assert 0.6 < late.on_time_rate < 0.7
    bad = history.get("BAD")
    assert bad.default_count == 1


def test_unknown_or_blank_merchant_has_no_profile(history: HistoryStore):
    assert history.get("NOPE") is None
    assert history.get("") is None


def test_volume_trend_and_recency(history: HistoryStore):
    good = history.get("GOOD")
    assert good.days_since_last_transaction == 6
    assert good.transactions_last_30d == 3
    assert good.volume_trend is not None and good.volume_trend > 0


def test_real_dataset_loads():
    store = HistoryStore.from_csv()
    assert len(store) == 60
    assert store.get("M-1001").transactions > 50
