from __future__ import annotations

from datetime import date

import pytest

from app.engine import DecisionEngine
from app.history import HistoryStore
from app.policy import load_policy
from app.schemas import DecisionRequest

AS_OF = date(2026, 8, 31)


def _txn(mid: str, day: str, amount: float, status: str = "on_time", financed: int = 1, days_to_repay="20"):
    return {
        "transaction_id": f"T-{mid}-{day}-{amount}",
        "merchant_id": mid,
        "date": day,
        "amount_sar": amount,
        "financed": financed,
        "term_days": 30 if financed else "",
        "days_to_repay": days_to_repay if status in ("on_time", "late") else "",
        "status": status if financed else "cash",
    }


@pytest.fixture(scope="session")
def rows() -> list[dict]:
    """Hand-built history: one perfect payer, one late payer, one defaulter, one tiny file."""
    good = [_txn("GOOD", f"2026-0{m}-{d:02d}", 10_000) for m in range(3, 9) for d in (5, 15, 25)]  # 18 orders
    late = [_txn("LATE", f"2026-0{m}-{d:02d}", 8_000, status="late" if d == 15 else "on_time",
                 days_to_repay="40" if d == 15 else "20") for m in range(3, 9) for d in (5, 15, 25)]
    bad = [_txn("BAD", f"2026-0{m}-10", 6_000, status="default" if m == 7 else "on_time") for m in range(3, 9)]
    thin = [_txn("THIN", "2026-08-20", 5_000)]
    return good + late + bad + thin


@pytest.fixture(scope="session")
def history(rows) -> HistoryStore:
    return HistoryStore.from_rows(rows, as_of=AS_OF)


@pytest.fixture(scope="session")
def policy():
    return load_policy()


@pytest.fixture(scope="session")
def engine(history, policy) -> DecisionEngine:
    return DecisionEngine(history=history, policy=policy)


@pytest.fixture
def base_request() -> dict:
    """The exact example from the case study brief."""
    return {
        "merchant_id": "",
        "merchant_business_description": "A small grocery store in a residential area of Riyadh, operating for 5 years.",
        "risk_tier": "B",
        "credit_limit": 50000,
        "current_exposure": 30000,
        "transaction_amount": 12000,
        "monthly_purchase_volume": 65000,
        "inventory_level": {"sku_A": 100, "sku_B": 50, "sku_C": 200},
    }


def make(base: dict, **overrides) -> DecisionRequest:
    return DecisionRequest(**{**base, **overrides})
