"""Request / response contracts for POST /decision."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Decision = Literal["APPROVED", "PARTIALLY_APPROVED", "DECLINED"]


class DecisionRequest(BaseModel):
    merchant_id: str = Field(default="", description="Partner-side merchant identifier")
    merchant_business_description: str = ""
    risk_tier: str = Field(description="Pre-scoring tier A (best) to E (worst)")
    credit_limit: float = Field(ge=0, description="Revolving limit in SAR")
    current_exposure: float = Field(ge=0, description="Outstanding financed balance in SAR")
    transaction_amount: float = Field(gt=0, description="Requested purchase amount in SAR")
    monthly_purchase_volume: float = Field(ge=0, description="Typical monthly purchases in SAR")
    inventory_level: dict[str, int] = Field(default_factory=dict)

    @field_validator("risk_tier")
    @classmethod
    def _normalise_tier(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in {"A", "B", "C", "D", "E"}:
            raise ValueError("risk_tier must be one of A, B, C, D, E")
        return v

    @field_validator("inventory_level")
    @classmethod
    def _non_negative_inventory(cls, v: dict[str, int]) -> dict[str, int]:
        if any(q < 0 for q in v.values()):
            raise ValueError("inventory quantities must be >= 0")
        return v


class Factor(BaseModel):
    code: str
    description: str
    impact: float = Field(description="Score points contributed (+/-); 0 for hard rules")


class HistorySummary(BaseModel):
    transactions: int
    financed_transactions: int
    on_time_rate: float | None
    late_count: int
    default_count: int
    average_amount: float | None
    volume_trend: float | None
    days_since_last_transaction: int | None


class DecisionResponse(BaseModel):
    decision: Decision
    approved_amount: float
    interest_rate: float = Field(description="Flat financing fee in % for the repayment term")
    repayment_terms: str
    reason: str
    # --- explainability / audit extras (superset of the required contract) ---
    decision_id: str
    score: int
    risk_band: str
    available_credit: float
    factors: list[Factor]
    policy_version: str
    merchant_history: HistorySummary | None
    processing_time_ms: float
