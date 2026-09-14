"""Credit policy configuration.

Everything a risk officer might want to tune lives in ``policy.json`` (versioned),
not in code. The engine reads it once at startup; swapping the file and restarting
(or calling ``load_policy`` again) changes behaviour without a deploy of new logic.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_POLICY_PATH = Path(__file__).with_name("policy.json")


@dataclass(frozen=True)
class Band:
    name: str
    min_score: int
    approval_cap: float
    rate_adder_pct: float


@dataclass(frozen=True)
class Policy:
    version: str
    currency: str
    min_ticket: float
    min_partial_fraction: float
    rounding: int
    max_defaults: int
    history_confidence_orders: int
    eligible_tiers: tuple[str, ...]
    tier_base_score: dict[str, int]
    tier_base_rate_pct: dict[str, float]
    tier_term_days: dict[str, int]
    bands: tuple[Band, ...]
    fraud_max_amount_to_monthly_volume: float
    fraud_max_amount_to_historical_avg: float
    good_payer_min_on_time_rate: float
    good_payer_min_settled_orders: int
    good_payer_term_extension_days: int
    good_payer_max_term_days: int

    def band_for(self, score: int) -> Band:
        for band in self.bands:  # bands are sorted high → low by min_score
            if score >= band.min_score:
                return band
        return self.bands[-1]


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> Policy:
    raw = json.loads(Path(path).read_text())
    bands = tuple(
        sorted((Band(**b) for b in raw["bands"]), key=lambda b: b.min_score, reverse=True)
    )
    return Policy(
        version=raw["version"],
        currency=raw["currency"],
        min_ticket=float(raw["min_ticket"]),
        min_partial_fraction=float(raw["min_partial_fraction"]),
        rounding=int(raw["rounding"]),
        max_defaults=int(raw.get("max_defaults", 0)),
        history_confidence_orders=int(raw.get("history_confidence_orders", 10)),
        eligible_tiers=tuple(raw["eligible_tiers"]),
        tier_base_score=raw["tier_base_score"],
        tier_base_rate_pct=raw["tier_base_rate_pct"],
        tier_term_days=raw["tier_term_days"],
        bands=bands,
        fraud_max_amount_to_monthly_volume=float(raw["fraud"]["max_amount_to_monthly_volume"]),
        fraud_max_amount_to_historical_avg=float(raw["fraud"]["max_amount_to_historical_avg"]),
        good_payer_min_on_time_rate=float(raw["good_payer"]["min_on_time_rate"]),
        good_payer_min_settled_orders=int(raw["good_payer"].get("min_settled_orders", 10)),
        good_payer_term_extension_days=int(raw["good_payer"]["term_extension_days"]),
        good_payer_max_term_days=int(raw["good_payer"]["max_term_days"]),
    )
