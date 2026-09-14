"""The decision engine: features → hard rules → score → sizing → pricing → explanation.

Design choice: a transparent *rules + additive score* model rather than ML.
Every point of the score is attributable to a named factor, which is what a
regulator (SAMA), a merchant, or an ops analyst needs to see. The same feature
vector is logged so a statistical model can be trained later on real outcomes.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from time import perf_counter

from .history import HistoryStore, MerchantProfile
from .policy import Policy
from .schemas import DecisionRequest, DecisionResponse, Factor, HistorySummary


# --------------------------------------------------------------------------- features
@dataclass
class Features:
    tier: str
    amount: float
    credit_limit: float
    exposure: float
    available_credit: float
    utilisation_after: float | None      # (exposure + amount) / limit
    amount_to_monthly: float | None      # amount / monthly purchase volume
    amount_to_hist_avg: float | None     # amount / historical average ticket
    inventory_units: int
    inventory_skus: int
    profile: MerchantProfile | None


def build_features(req: DecisionRequest, profile: MerchantProfile | None) -> Features:
    available = max(req.credit_limit - req.current_exposure, 0.0)
    return Features(
        tier=req.risk_tier,
        amount=req.transaction_amount,
        credit_limit=req.credit_limit,
        exposure=req.current_exposure,
        available_credit=available,
        utilisation_after=((req.current_exposure + req.transaction_amount) / req.credit_limit)
        if req.credit_limit > 0 else None,
        amount_to_monthly=(req.transaction_amount / req.monthly_purchase_volume)
        if req.monthly_purchase_volume > 0 else None,
        amount_to_hist_avg=(req.transaction_amount / profile.average_amount)
        if profile and profile.average_amount > 0 else None,
        inventory_units=sum(req.inventory_level.values()),
        inventory_skus=len(req.inventory_level),
        profile=profile,
    )


# --------------------------------------------------------------------------- hard rules
@dataclass
class RuleHit:
    code: str
    description: str


def evaluate_hard_rules(f: Features, policy: Policy) -> list[RuleHit]:
    """Policy gates. Any hit is an immediate DECLINE regardless of score."""
    hits: list[RuleHit] = []
    if f.tier not in policy.eligible_tiers:
        hits.append(RuleHit("TIER_NOT_ELIGIBLE", f"Risk tier {f.tier} is not eligible for financing under policy {policy.version}."))
    if f.amount < policy.min_ticket:
        hits.append(RuleHit("BELOW_MIN_TICKET", f"Transaction amount is below the minimum financeable ticket of {policy.currency} {policy.min_ticket:,.0f}."))
    if f.available_credit <= 0:
        hits.append(RuleHit("NO_AVAILABLE_CREDIT", f"Current exposure ({policy.currency} {f.exposure:,.0f}) already meets or exceeds the credit limit ({policy.currency} {f.credit_limit:,.0f})."))
    if f.profile and f.profile.default_count > policy.max_defaults:
        hits.append(RuleHit("PRIOR_DEFAULT", f"Merchant has {f.profile.default_count} defaulted financed transaction(s) in the last 12 months (policy allows {policy.max_defaults})."))
    if f.amount_to_monthly is not None and f.amount_to_monthly > policy.fraud_max_amount_to_monthly_volume:
        hits.append(RuleHit("FRAUD_AMOUNT_VS_VOLUME", f"Transaction is {f.amount_to_monthly:.1f}x the merchant's monthly purchase volume; flagged as anomalous."))
    if f.amount_to_hist_avg is not None and f.amount_to_hist_avg > policy.fraud_max_amount_to_historical_avg:
        hits.append(RuleHit("FRAUD_AMOUNT_VS_HISTORY", f"Transaction is {f.amount_to_hist_avg:.1f}x the merchant's historical average ticket; flagged as anomalous."))
    return hits


# --------------------------------------------------------------------------- scoring
def compute_score(f: Features, policy: Policy) -> tuple[int, list[Factor]]:
    factors: list[Factor] = []

    def add(code: str, description: str, impact: float) -> None:
        if impact != 0:
            factors.append(Factor(code=code, description=description, impact=round(impact, 1)))

    base = policy.tier_base_score.get(f.tier, 0)
    factors.append(Factor(code="TIER_BASE", description=f"Base score for pre-scoring tier {f.tier}.", impact=base))

    p = f.profile
    if p is None:
        add("THIN_FILE", "No transaction history on file; applying thin-file penalty.", -8)
    else:
        rate = p.on_time_rate
        if rate is not None:
            # Confidence-weighted: 100% on-time across 2 orders proves far less than across 50.
            confidence = min(1.0, p.settled_financed / policy.history_confidence_orders)
            impact = max(-20.0, min(12.0, (rate - 0.85) * 100)) * (confidence if rate >= 0.85 else 1.0)
            add("REPAYMENT_DISCIPLINE", f"On-time repayment rate {rate:.0%} across {p.settled_financed} settled financed orders.", impact)
        if p.late_count:
            add("LATE_PAYMENTS", f"{p.late_count} late repayment(s) in the last 12 months.", -min(12, 3 * p.late_count))
        if p.volume_trend is not None:
            if p.volume_trend >= 1.10:
                add("VOLUME_GROWING", f"Purchase volume up {p.volume_trend - 1:.0%} over the last 90 days vs the prior 90.", 4)
            elif p.volume_trend < 0.80:
                add("VOLUME_SHRINKING", f"Purchase volume down {1 - p.volume_trend:.0%} over the last 90 days vs the prior 90.", -6)
        if p.transactions_last_30d == 0 and p.days_since_last_transaction > 60:
            add("DORMANT", f"No purchases in {p.days_since_last_transaction} days.", -5)
        if p.transactions < 10:
            add("SHORT_HISTORY", f"Only {p.transactions} transactions on file.", -4)

    if f.utilisation_after is not None:
        if f.utilisation_after > 1.0:
            add("OVER_LIMIT", f"Request would take utilisation to {f.utilisation_after:.0%} of the limit.", -8)
        elif f.utilisation_after > 0.85:
            add("HIGH_UTILISATION", f"Request would take utilisation to {f.utilisation_after:.0%} of the limit.", -5)
        elif f.utilisation_after < 0.5:
            add("LOW_UTILISATION", f"Utilisation stays at {f.utilisation_after:.0%} of the limit.", 3)

    if f.amount_to_monthly is not None:
        if f.amount_to_monthly > 0.5:
            add("LARGE_VS_MONTHLY", f"Amount is {f.amount_to_monthly:.0%} of monthly purchase volume.", -10)
        elif f.amount_to_monthly > 0.3:
            add("SIZEABLE_VS_MONTHLY", f"Amount is {f.amount_to_monthly:.0%} of monthly purchase volume.", -4)
        elif f.amount_to_monthly <= 0.15:
            add("ROUTINE_ORDER", f"Amount is {f.amount_to_monthly:.0%} of monthly purchase volume, a routine order.", 2)

    if f.amount_to_hist_avg is not None:
        if f.amount_to_hist_avg > 3:
            add("UNUSUALLY_LARGE", f"Amount is {f.amount_to_hist_avg:.1f}x the merchant's average ticket.", -8)
        elif f.amount_to_hist_avg > 2:
            add("ABOVE_AVERAGE", f"Amount is {f.amount_to_hist_avg:.1f}x the merchant's average ticket.", -4)

    if f.inventory_skus >= 3:
        add("SKU_DIVERSITY", f"Inventory spans {f.inventory_skus} SKUs; diversified stock lowers concentration risk.", 2)

    score = int(round(max(0.0, min(100.0, sum(x.impact for x in factors)))))
    return score, factors


# --------------------------------------------------------------------------- sizing & pricing
def _round_down(amount: float, step: int) -> float:
    return float(math.floor(amount / step) * step) if step > 0 else amount


def size_approval(f: Features, score: int, policy: Policy) -> tuple[str, float, str]:
    """Returns (decision, approved_amount, sizing_driver)."""
    band = policy.band_for(score)
    if band.approval_cap <= 0:
        return "DECLINED", 0.0, "RISK_BAND"
    cap_by_risk = f.amount * band.approval_cap
    approved = _round_down(min(f.amount, f.available_credit, cap_by_risk), policy.rounding)
    if approved >= f.amount:
        return "APPROVED", approved, "FULL"
    min_useful = max(policy.min_ticket, f.amount * policy.min_partial_fraction)
    if approved < min_useful:
        return "DECLINED", 0.0, "PARTIAL_TOO_SMALL"
    driver = "AVAILABLE_CREDIT" if f.available_credit < cap_by_risk else "RISK_BAND"
    return "PARTIALLY_APPROVED", approved, driver


def price(f: Features, score: int, policy: Policy) -> tuple[float, int]:
    band = policy.band_for(score)
    rate = policy.tier_base_rate_pct[f.tier] + band.rate_adder_pct
    term = policy.tier_term_days[f.tier]
    p = f.profile
    if (band.name == "LOW" and p and p.on_time_rate is not None
            and p.settled_financed >= policy.good_payer_min_settled_orders
            and p.on_time_rate >= policy.good_payer_min_on_time_rate):
        term = min(term + policy.good_payer_term_extension_days, policy.good_payer_max_term_days)
    return round(rate, 2), term


# --------------------------------------------------------------------------- explanation
def explain(decision: str, driver: str, f: Features, approved: float, score: int,
            band: str, factors: list[Factor], hits: list[RuleHit], policy: Policy) -> str:
    cur = policy.currency
    if hits:
        return "Declined by policy rule: " + " ".join(h.description for h in hits)
    negatives = sorted((x for x in factors if x.impact < 0), key=lambda x: x.impact)
    positives = sorted((x for x in factors if x.impact > 0 and x.code != "TIER_BASE"), key=lambda x: -x.impact)
    drivers = "; ".join(x.description.rstrip(".") for x in (negatives[:2] or positives[:2]))
    if decision == "APPROVED":
        return f"Approved in full. Risk score {score} ({band}). {drivers}." if drivers else f"Approved in full. Risk score {score} ({band})."
    if decision == "PARTIALLY_APPROVED":
        if driver == "AVAILABLE_CREDIT":
            return (f"The transaction amount exceeds the remaining credit limit ({cur} {f.available_credit:,.0f} available). "
                    f"The approved amount is based on the available credit. Risk score {score} ({band}).")
        return (f"Risk score {score} ({band}) caps financing at {policy.band_for(score).approval_cap:.0%} of the request. "
                f"Approved {cur} {approved:,.0f} of {cur} {f.amount:,.0f}. Drivers: {drivers}.")
    if driver == "PARTIAL_TOO_SMALL":
        return (f"Only {cur} {f.available_credit:,.0f} of credit is available, which is below the minimum useful partial approval "
                f"for a {cur} {f.amount:,.0f} order. Risk score {score} ({band}).")
    return f"Risk score {score} ({band}) is below the approval threshold. Drivers: {drivers}."


def _history_summary(p: MerchantProfile | None) -> HistorySummary | None:
    if p is None:
        return None
    return HistorySummary(
        transactions=p.transactions,
        financed_transactions=p.financed_transactions,
        on_time_rate=round(p.on_time_rate, 3) if p.on_time_rate is not None else None,
        late_count=p.late_count,
        default_count=p.default_count,
        average_amount=round(p.average_amount, 2),
        volume_trend=p.volume_trend,
        days_since_last_transaction=p.days_since_last_transaction,
    )


# --------------------------------------------------------------------------- orchestration
@dataclass
class DecisionTrace:
    """Everything needed to audit a decision. Emitted to the decision log."""
    response: DecisionResponse
    request: DecisionRequest
    rule_hits: list[RuleHit] = field(default_factory=list)


class DecisionEngine:
    def __init__(self, history: HistoryStore, policy: Policy):
        self.history = history
        self.policy = policy

    def decide(self, req: DecisionRequest) -> DecisionTrace:
        t0 = perf_counter()
        profile = self.history.get(req.merchant_id)
        f = build_features(req, profile)
        hits = evaluate_hard_rules(f, self.policy)
        score, factors = compute_score(f, self.policy)
        band = self.policy.band_for(score).name

        if hits:
            decision, approved, driver = "DECLINED", 0.0, "HARD_RULE"
            factors = [Factor(code=h.code, description=h.description, impact=0.0) for h in hits] + factors
        else:
            decision, approved, driver = size_approval(f, score, self.policy)

        rate, term = price(f, score, self.policy) if decision != "DECLINED" else (0.0, 0)
        reason = explain(decision, driver, f, approved, score, band, factors, hits, self.policy)

        response = DecisionResponse(
            decision=decision,
            approved_amount=approved,
            interest_rate=rate,
            repayment_terms=f"{term} days" if term else "n/a",
            reason=reason,
            decision_id=str(uuid.uuid4()),
            score=score,
            risk_band=band,
            available_credit=f.available_credit,
            factors=factors,
            policy_version=self.policy.version,
            merchant_history=_history_summary(profile),
            processing_time_ms=round((perf_counter() - t0) * 1000, 3),
        )
        return DecisionTrace(response=response, request=req, rule_hits=hits)
