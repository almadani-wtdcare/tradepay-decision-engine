"""Historical transaction store.

Loads the synthetic CSV once and pre-aggregates a behavioural profile per merchant so the
hot path is a dictionary lookup (microseconds). In production this becomes a feature
store keyed by merchant_id (e.g. Redis/DynamoDB) fed by the ingestion pipeline.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TRANSACTIONS_CSV = DATA_DIR / "transactions.csv"


@dataclass(frozen=True)
class MerchantProfile:
    merchant_id: str
    transactions: int
    financed_transactions: int
    on_time_count: int
    late_count: int
    default_count: int
    average_amount: float
    max_amount: float
    average_days_to_repay: float | None
    volume_trend: float | None            # last 90d volume / prior 90d volume
    days_since_last_transaction: int
    transactions_last_30d: int

    @property
    def settled_financed(self) -> int:
        return self.on_time_count + self.late_count + self.default_count

    @property
    def on_time_rate(self) -> float | None:
        return self.on_time_count / self.settled_financed if self.settled_financed else None


def _profile_from_rows(merchant_id: str, rows: list[dict], as_of: date) -> MerchantProfile:
    amounts = [float(r["amount_sar"]) for r in rows]
    dates = [date.fromisoformat(r["date"]) for r in rows]
    financed = [r for r in rows if str(r["financed"]) in ("1", "True", "true")]
    on_time = sum(1 for r in financed if r["status"] == "on_time")
    late = sum(1 for r in financed if r["status"] == "late")
    default = sum(1 for r in financed if r["status"] == "default")
    repay_days = [float(r["days_to_repay"]) for r in financed if r["days_to_repay"] not in ("", None)]

    recent = sum(a for a, d in zip(amounts, dates) if (as_of - d).days < 90)
    prior = sum(a for a, d in zip(amounts, dates) if 90 <= (as_of - d).days < 180)
    trend = (recent / prior) if prior > 0 else None

    return MerchantProfile(
        merchant_id=merchant_id,
        transactions=len(rows),
        financed_transactions=len(financed),
        on_time_count=on_time,
        late_count=late,
        default_count=default,
        average_amount=sum(amounts) / len(amounts),
        max_amount=max(amounts),
        average_days_to_repay=(sum(repay_days) / len(repay_days)) if repay_days else None,
        volume_trend=round(trend, 3) if trend is not None else None,
        days_since_last_transaction=(as_of - max(dates)).days,
        transactions_last_30d=sum(1 for d in dates if (as_of - d).days < 30),
    )


class HistoryStore:
    def __init__(self, profiles: dict[str, MerchantProfile], as_of: date):
        self._profiles = profiles
        self.as_of = as_of

    @classmethod
    def from_rows(cls, rows: Iterable[dict], as_of: date | None = None) -> "HistoryStore":
        rows = list(rows)
        if not rows:
            return cls({}, as_of or date.today())
        as_of = as_of or max(date.fromisoformat(r["date"]) for r in rows)
        grouped: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            grouped[r["merchant_id"]].append(r)
        return cls({m: _profile_from_rows(m, rs, as_of) for m, rs in grouped.items()}, as_of)

    @classmethod
    def from_csv(cls, path: Path = TRANSACTIONS_CSV) -> "HistoryStore":
        with Path(path).open(newline="") as f:
            return cls.from_rows(csv.DictReader(f))

    def get(self, merchant_id: str) -> MerchantProfile | None:
        return self._profiles.get(merchant_id) if merchant_id else None

    def __len__(self) -> int:
        return len(self._profiles)
