"""Structured (JSON lines) decision logging.

One log record per decision carrying the full input, every factor with its point
contribution, the rule hits and the outcome. This is the audit trail: it can be
shipped unchanged to an append-only store (e.g. S3/BigQuery in KSA region) and
queried by decision_id when a merchant or a regulator asks "why?".
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from .engine import DecisionTrace


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "decision", None)
        if extra:
            payload["decision"] = extra
        return json.dumps(payload, default=str)


class StdoutHandler(logging.StreamHandler):
    """Resolves sys.stdout at emit time so redirected/captured stdout is honoured."""

    def __init__(self) -> None:
        super().__init__(stream=sys.stdout)

    @property
    def stream(self):  # type: ignore[override]
        return sys.stdout

    @stream.setter
    def stream(self, _value) -> None:
        pass


def configure_logging(level: str = "INFO") -> None:
    handler = StdoutHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


decision_logger = logging.getLogger("tradepay.decision")


def log_decision(trace: DecisionTrace) -> None:
    r = trace.response
    decision_logger.info(
        "decision %s %s score=%s approved=%s",
        r.decision_id, r.decision, r.score, r.approved_amount,
        extra={
            "decision": {
                "decision_id": r.decision_id,
                "policy_version": r.policy_version,
                "request": trace.request.model_dump(),
                "outcome": {
                    "decision": r.decision,
                    "approved_amount": r.approved_amount,
                    "interest_rate": r.interest_rate,
                    "repayment_terms": r.repayment_terms,
                    "score": r.score,
                    "risk_band": r.risk_band,
                    "available_credit": r.available_credit,
                },
                "rule_hits": [h.code for h in trace.rule_hits],
                "factors": [x.model_dump() for x in r.factors],
                "merchant_history": r.merchant_history.model_dump() if r.merchant_history else None,
                "reason": r.reason,
                "processing_time_ms": r.processing_time_ms,
            }
        },
    )
