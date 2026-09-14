"""FastAPI entrypoint for the TradePay decision support microservice."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from .engine import DecisionEngine
from .history import HistoryStore
from .logging_utils import configure_logging, log_decision
from .policy import load_policy
from .schemas import DecisionRequest, DecisionResponse


class _QuietAccessLog(logging.Filter):
    """Keep the access log readable during demos: drop health-check and favicon noise."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not ("/health " in msg or "/favicon.ico" in msg)


def build_engine() -> DecisionEngine:
    return DecisionEngine(history=HistoryStore.from_csv(), policy=load_policy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(os.getenv("LOG_LEVEL", "INFO"))
    logging.getLogger("uvicorn.access").addFilter(_QuietAccessLog())
    app.state.engine = build_engine()
    yield


app = FastAPI(
    title="TradePay Decision Engine",
    version="0.1.0",
    description="Real-time credit decision support for merchant purchase transactions.",
    lifespan=lifespan,
)


STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/demo")


@app.get("/demo", include_in_schema=False)
def demo() -> FileResponse:
    """Interactive demo page: preset scenarios, editable request, visual factor breakdown."""
    return FileResponse(STATIC_DIR / "demo.html", media_type="text/html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/health", tags=["ops"])
def health(request: Request) -> dict:
    engine: DecisionEngine = request.app.state.engine
    return {
        "status": "ok",
        "policy_version": engine.policy.version,
        "merchants_in_history": len(engine.history),
        "history_as_of": engine.history.as_of.isoformat(),
    }


@app.post("/decision", response_model=DecisionResponse, tags=["decisioning"])
def decision(payload: DecisionRequest, request: Request) -> DecisionResponse:
    engine: DecisionEngine = request.app.state.engine
    trace = engine.decide(payload)
    log_decision(trace)
    return trace.response


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
    return JSONResponse(status_code=500, content={"detail": "internal error", "type": type(exc).__name__})
