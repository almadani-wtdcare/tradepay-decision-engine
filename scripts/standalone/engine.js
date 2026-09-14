// JavaScript port of tradepay/app/engine.py — same rules, same score, same wording.
function fmt0(n) { return Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 }); }
function pct0(x) { return Math.round(x * 100) + '%'; }
function fix1(x) { return (Math.round(x * 10) / 10).toFixed(1); }
function round1(x) { return Math.round(x * 10) / 10; }
function pyRound(x) { // Python round-half-even on a float
  const f = Math.floor(x), d = x - f;
  if (d > 0.5) return f + 1; if (d < 0.5) return f; return f % 2 === 0 ? f : f + 1;
}
function bandFor(policy, score) {
  const bands = [...policy.bands].sort((a, b) => b.min_score - a.min_score);
  for (const b of bands) if (score >= b.min_score) return b;
  return bands[bands.length - 1];
}
function onTimeRate(p) { const s = p.on_time_count + p.late_count + p.default_count; return s ? p.on_time_count / s : null; }
function settled(p) { return p.on_time_count + p.late_count + p.default_count; }

function buildFeatures(req, p) {
  const available = Math.max(req.credit_limit - req.current_exposure, 0);
  return {
    tier: req.risk_tier, amount: req.transaction_amount, credit_limit: req.credit_limit, exposure: req.current_exposure,
    available_credit: available,
    utilisation_after: req.credit_limit > 0 ? (req.current_exposure + req.transaction_amount) / req.credit_limit : null,
    amount_to_monthly: req.monthly_purchase_volume > 0 ? req.transaction_amount / req.monthly_purchase_volume : null,
    amount_to_hist_avg: p && p.average_amount > 0 ? req.transaction_amount / p.average_amount : null,
    inventory_units: Object.values(req.inventory_level || {}).reduce((a, b) => a + b, 0),
    inventory_skus: Object.keys(req.inventory_level || {}).length, profile: p || null,
  };
}
function hardRules(f, policy) {
  const hits = [], cur = policy.currency;
  if (!policy.eligible_tiers.includes(f.tier)) hits.push({ code: 'TIER_NOT_ELIGIBLE', description: `Risk tier ${f.tier} is not eligible for financing under policy ${policy.version}.` });
  if (f.amount < policy.min_ticket) hits.push({ code: 'BELOW_MIN_TICKET', description: `Transaction amount is below the minimum financeable ticket of ${cur} ${fmt0(policy.min_ticket)}.` });
  if (f.available_credit <= 0) hits.push({ code: 'NO_AVAILABLE_CREDIT', description: `Current exposure (${cur} ${fmt0(f.exposure)}) already meets or exceeds the credit limit (${cur} ${fmt0(f.credit_limit)}).` });
  if (f.profile && f.profile.default_count > policy.max_defaults) hits.push({ code: 'PRIOR_DEFAULT', description: `Merchant has ${f.profile.default_count} defaulted financed transaction(s) in the last 12 months (policy allows ${policy.max_defaults}).` });
  if (f.amount_to_monthly !== null && f.amount_to_monthly > policy.fraud.max_amount_to_monthly_volume) hits.push({ code: 'FRAUD_AMOUNT_VS_VOLUME', description: `Transaction is ${fix1(f.amount_to_monthly)}x the merchant's monthly purchase volume; flagged as anomalous.` });
  if (f.amount_to_hist_avg !== null && f.amount_to_hist_avg > policy.fraud.max_amount_to_historical_avg) hits.push({ code: 'FRAUD_AMOUNT_VS_HISTORY', description: `Transaction is ${fix1(f.amount_to_hist_avg)}x the merchant's historical average ticket; flagged as anomalous.` });
  return hits;
}
function computeScore(f, policy) {
  const factors = [];
  const add = (code, description, impact) => { if (impact !== 0) factors.push({ code, description, impact: round1(impact) }); };
  const base = policy.tier_base_score[f.tier] || 0;
  factors.push({ code: 'TIER_BASE', description: `Base score for pre-scoring tier ${f.tier}.`, impact: base });
  const p = f.profile;
  if (!p) add('THIN_FILE', 'No transaction history on file; applying thin-file penalty.', -8);
  else {
    const rate = onTimeRate(p);
    if (rate !== null) {
      const confidence = Math.min(1, settled(p) / policy.history_confidence_orders);
      const impact = Math.max(-20, Math.min(12, (rate - 0.85) * 100)) * (rate >= 0.85 ? confidence : 1);
      add('REPAYMENT_DISCIPLINE', `On-time repayment rate ${pct0(rate)} across ${settled(p)} settled financed orders.`, impact);
    }
    if (p.late_count) add('LATE_PAYMENTS', `${p.late_count} late repayment(s) in the last 12 months.`, -Math.min(12, 3 * p.late_count));
    if (p.volume_trend !== null && p.volume_trend !== undefined) {
      if (p.volume_trend >= 1.10) add('VOLUME_GROWING', `Purchase volume up ${pct0(p.volume_trend - 1)} over the last 90 days vs the prior 90.`, 4);
      else if (p.volume_trend < 0.80) add('VOLUME_SHRINKING', `Purchase volume down ${pct0(1 - p.volume_trend)} over the last 90 days vs the prior 90.`, -6);
    }
    if (p.transactions_last_30d === 0 && p.days_since_last_transaction > 60) add('DORMANT', `No purchases in ${p.days_since_last_transaction} days.`, -5);
    if (p.transactions < 10) add('SHORT_HISTORY', `Only ${p.transactions} transactions on file.`, -4);
  }
  if (f.utilisation_after !== null) {
    if (f.utilisation_after > 1.0) add('OVER_LIMIT', `Request would take utilisation to ${pct0(f.utilisation_after)} of the limit.`, -8);
    else if (f.utilisation_after > 0.85) add('HIGH_UTILISATION', `Request would take utilisation to ${pct0(f.utilisation_after)} of the limit.`, -5);
    else if (f.utilisation_after < 0.5) add('LOW_UTILISATION', `Utilisation stays at ${pct0(f.utilisation_after)} of the limit.`, 3);
  }
  if (f.amount_to_monthly !== null) {
    if (f.amount_to_monthly > 0.5) add('LARGE_VS_MONTHLY', `Amount is ${pct0(f.amount_to_monthly)} of monthly purchase volume.`, -10);
    else if (f.amount_to_monthly > 0.3) add('SIZEABLE_VS_MONTHLY', `Amount is ${pct0(f.amount_to_monthly)} of monthly purchase volume.`, -4);
    else if (f.amount_to_monthly <= 0.15) add('ROUTINE_ORDER', `Amount is ${pct0(f.amount_to_monthly)} of monthly purchase volume, a routine order.`, 2);
  }
  if (f.amount_to_hist_avg !== null) {
    if (f.amount_to_hist_avg > 3) add('UNUSUALLY_LARGE', `Amount is ${fix1(f.amount_to_hist_avg)}x the merchant's average ticket.`, -8);
    else if (f.amount_to_hist_avg > 2) add('ABOVE_AVERAGE', `Amount is ${fix1(f.amount_to_hist_avg)}x the merchant's average ticket.`, -4);
  }
  if (f.inventory_skus >= 3) add('SKU_DIVERSITY', `Inventory spans ${f.inventory_skus} SKUs; diversified stock lowers concentration risk.`, 2);
  const sum = factors.reduce((a, x) => a + x.impact, 0);
  const score = pyRound(Math.max(0, Math.min(100, sum)));
  return { score, factors };
}
function roundDown(a, step) { return step > 0 ? Math.floor(a / step) * step : a; }
function sizeApproval(f, score, policy) {
  const band = bandFor(policy, score);
  if (band.approval_cap <= 0) return ['DECLINED', 0, 'RISK_BAND'];
  const cap = f.amount * band.approval_cap;
  const approved = roundDown(Math.min(f.amount, f.available_credit, cap), policy.rounding);
  if (approved >= f.amount) return ['APPROVED', approved, 'FULL'];
  const minUseful = Math.max(policy.min_ticket, f.amount * policy.min_partial_fraction);
  if (approved < minUseful) return ['DECLINED', 0, 'PARTIAL_TOO_SMALL'];
  return ['PARTIALLY_APPROVED', approved, f.available_credit < cap ? 'AVAILABLE_CREDIT' : 'RISK_BAND'];
}
function price(f, score, policy) {
  const band = bandFor(policy, score);
  const rate = Math.round((policy.tier_base_rate_pct[f.tier] + band.rate_adder_pct) * 100) / 100;
  let term = policy.tier_term_days[f.tier];
  const p = f.profile, gp = policy.good_payer;
  if (band.name === 'LOW' && p && onTimeRate(p) !== null && settled(p) >= gp.min_settled_orders && onTimeRate(p) >= gp.min_on_time_rate) term = Math.min(term + gp.term_extension_days, gp.max_term_days);
  return [rate, term];
}
function explain(decision, driver, f, approved, score, band, factors, hits, policy) {
  const cur = policy.currency;
  if (hits.length) return 'Declined by policy rule: ' + hits.map(h => h.description).join(' ');
  const negatives = factors.filter(x => x.impact < 0).sort((a, b) => a.impact - b.impact);
  const positives = factors.filter(x => x.impact > 0 && x.code !== 'TIER_BASE').sort((a, b) => b.impact - a.impact);
  const drivers = (negatives.length ? negatives : positives).slice(0, 2).map(x => x.description.replace(/\.$/, '')).join('; ');
  if (decision === 'APPROVED') return drivers ? `Approved in full. Risk score ${score} (${band}). ${drivers}.` : `Approved in full. Risk score ${score} (${band}).`;
  if (decision === 'PARTIALLY_APPROVED') {
    if (driver === 'AVAILABLE_CREDIT') return `The transaction amount exceeds the remaining credit limit (${cur} ${fmt0(f.available_credit)} available). The approved amount is based on the available credit. Risk score ${score} (${band}).`;
    return `Risk score ${score} (${band}) caps financing at ${pct0(bandFor(policy, score).approval_cap)} of the request. Approved ${cur} ${fmt0(approved)} of ${cur} ${fmt0(f.amount)}. Drivers: ${drivers}.`;
  }
  if (driver === 'PARTIAL_TOO_SMALL') return `Only ${cur} ${fmt0(f.available_credit)} of credit is available, which is below the minimum useful partial approval for a ${cur} ${fmt0(f.amount)} order. Risk score ${score} (${band}).`;
  return `Risk score ${score} (${band}) is below the approval threshold. Drivers: ${drivers}.`;
}
function decide(req, profiles, policy) {
  const t0 = (typeof performance !== 'undefined' ? performance : Date).now();
  const tier = String(req.risk_tier || '').trim().toUpperCase();
  const r = { ...req, risk_tier: tier };
  const p = r.merchant_id ? profiles[r.merchant_id] || null : null;
  const f = buildFeatures(r, p);
  const hits = hardRules(f, policy);
  let { score, factors } = computeScore(f, policy);
  const band = bandFor(policy, score).name;
  let decision, approved, driver;
  if (hits.length) { [decision, approved, driver] = ['DECLINED', 0, 'HARD_RULE']; factors = [...hits.map(h => ({ ...h, impact: 0 })), ...factors]; }
  else [decision, approved, driver] = sizeApproval(f, score, policy);
  const [rate, term] = decision !== 'DECLINED' ? price(f, score, policy) : [0, 0];
  const reason = explain(decision, driver, f, approved, score, band, factors, hits, policy);
  return { decision, approved_amount: approved, interest_rate: rate, repayment_terms: term ? `${term} days` : 'n/a', reason,
    decision_id: (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID() : String(Math.random()).slice(2),
    score, risk_band: band, available_credit: f.available_credit, factors, policy_version: policy.version,
    merchant_history: p ? { transactions: p.transactions, financed_transactions: p.financed_transactions, on_time_rate: onTimeRate(p) === null ? null : Math.round(onTimeRate(p) * 1000) / 1000, late_count: p.late_count, default_count: p.default_count, average_amount: Math.round(p.average_amount * 100) / 100, volume_trend: p.volume_trend, days_since_last_transaction: p.days_since_last_transaction } : null,
    processing_time_ms: Math.round(((typeof performance !== 'undefined' ? performance : Date).now() - t0) * 1000) / 1000 };
}
if (typeof module !== 'undefined') module.exports = { decide };
