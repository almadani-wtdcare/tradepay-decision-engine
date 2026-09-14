"""Deterministic synthetic transaction history for a sample of TradePay merchants.

Run:  python -m data.generate_history
Writes data/merchants.csv and data/transactions.csv (12 months ending 2026-08-31).

Six behavioural archetypes are simulated so that the decision engine has real
signal to learn from (repayment discipline, growth, over-stretching, defaults,
and "thin file" merchants with almost no history).
"""
from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

SEED = 20260831
AS_OF = date(2026, 8, 31)
START = AS_OF - timedelta(days=365)
DATA_DIR = Path(__file__).resolve().parent

CITIES = ["Riyadh", "Jeddah", "Dammam", "Makkah", "Madinah", "Khobar"]
SEGMENTS = ["baqala", "mini_market", "horeca"]


@dataclass(frozen=True)
class Archetype:
    name: str
    tier: str
    monthly_volume: tuple[int, int]      # SAR range
    orders_per_month: tuple[int, int]
    p_late: float                        # probability a financed order is repaid late
    p_default: float                     # probability a financed order is never repaid
    growth: float                        # monthly volume multiplier trend
    months_active: int                   # how many months of history exist


ARCHETYPES: list[tuple[Archetype, range]] = [
    (Archetype("prime", "A", (150_000, 400_000), (6, 10), 0.02, 0.0, 1.01, 12), range(1001, 1013)),
    (Archetype("steady", "B", (60_000, 150_000), (4, 8), 0.08, 0.0, 1.00, 12), range(1013, 1031)),
    (Archetype("growing", "B", (40_000, 90_000), (3, 6), 0.10, 0.0, 1.06, 12), range(1031, 1043)),
    (Archetype("stretched", "C", (50_000, 120_000), (4, 8), 0.30, 0.02, 0.97, 12), range(1043, 1051)),
    (Archetype("delinquent", "D", (30_000, 80_000), (3, 6), 0.45, 0.15, 0.90, 12), range(1051, 1057)),
    (Archetype("thin", "C", (20_000, 60_000), (1, 2), 0.10, 0.0, 1.00, 2), range(1057, 1061)),
]


def generate() -> tuple[list[dict], list[dict]]:
    rng = random.Random(SEED)
    merchants: list[dict] = []
    transactions: list[dict] = []
    txn_seq = 1

    for archetype, id_range in ARCHETYPES:
        for n in id_range:
            merchant_id = f"M-{n}"
            base_volume = rng.randint(*archetype.monthly_volume)
            segment = rng.choice(SEGMENTS)
            credit_limit = int(round(base_volume * rng.uniform(0.35, 0.6), -3))
            merchants.append(
                {
                    "merchant_id": merchant_id,
                    "segment": segment,
                    "city": rng.choice(CITIES),
                    "risk_tier": archetype.tier,
                    "credit_limit_sar": credit_limit,
                    "archetype": archetype.name,
                    "months_active": archetype.months_active,
                }
            )

            first_month = 12 - archetype.months_active
            for month_idx in range(first_month, 12):
                month_start = START + timedelta(days=month_idx * 30)
                volume = base_volume * (archetype.growth ** (month_idx - first_month))
                orders = rng.randint(*archetype.orders_per_month)
                for _ in range(orders):
                    amount = max(300, int(rng.gauss(volume / orders, volume / orders * 0.35)))
                    day = month_start + timedelta(days=rng.randint(0, 29))
                    if day > AS_OF:
                        continue
                    financed = rng.random() < 0.7
                    term_days = 30 if archetype.tier in ("A", "B") else 21
                    status, days_to_repay = "cash", ""
                    if financed:
                        roll = rng.random()
                        if roll < archetype.p_default:
                            status, days_to_repay = "default", ""
                        elif roll < archetype.p_default + archetype.p_late:
                            status = "late"
                            days_to_repay = term_days + rng.randint(3, 25)
                        else:
                            status = "on_time"
                            days_to_repay = rng.randint(max(5, term_days - 15), term_days)
                        # Very recent financed orders may still be open.
                        if status != "default" and (AS_OF - day).days < int(days_to_repay or 0):
                            status, days_to_repay = "open", ""
                    transactions.append(
                        {
                            "transaction_id": f"T-{txn_seq:06d}",
                            "merchant_id": merchant_id,
                            "date": day.isoformat(),
                            "amount_sar": amount,
                            "financed": int(financed),
                            "term_days": term_days if financed else "",
                            "days_to_repay": days_to_repay,
                            "status": status,
                        }
                    )
                    txn_seq += 1

    transactions.sort(key=lambda t: (t["date"], t["transaction_id"]))
    return merchants, transactions


def write(merchants: list[dict], transactions: list[dict]) -> None:
    with (DATA_DIR / "merchants.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(merchants[0].keys()))
        w.writeheader()
        w.writerows(merchants)
    with (DATA_DIR / "transactions.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(transactions[0].keys()))
        w.writeheader()
        w.writerows(transactions)


if __name__ == "__main__":
    m, t = generate()
    write(m, t)
    print(f"wrote {len(m)} merchants and {len(t)} transactions to {DATA_DIR}")
