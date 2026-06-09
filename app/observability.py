"""Structured logging + MLflow tracing (the model-audit layer).

`mlflow.dspy.autolog()` records every model call — input, rendered prompt, model, output,
tokens, latency — so each extraction is reproducible. That is the model-audit layer; the
business-audit layer (document state changes) lives in the job store's audit_events.
"""
from __future__ import annotations

import logging
import os

import structlog

from app.config import settings

# Trace export must NEVER block the extraction worker, so export on a background queue.
# (On Databricks Free Edition the heavy trace *attachment* upload is egress-blocked and
# retries in the background; async keeps that off the worker thread. The core trace still
# persists, so the model-audit layer works.) Set before mlflow is imported.
os.environ.setdefault("MLFLOW_ENABLE_ASYNC_TRACE_LOGGING", "true")


def configure(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", level=level)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )
    # Tracing is opt-in via MLFLOW_EXPERIMENT (set it where the trace backend is reachable —
    # locally or a paid workspace). When on, it records every LLM/VLM call (input, prompt,
    # output, tokens, latency) — the model-audit layer — but asynchronously, so a slow or
    # blocked exporter can't add to job latency.
    if not settings.mlflow_experiment:
        get_logger(__name__).info("mlflow_tracing_disabled")
        return
    try:
        import mlflow

        try:
            mlflow.config.enable_async_logging()  # export off the worker thread
        except Exception:
            pass
        mlflow.set_tracking_uri("databricks")
        mlflow.set_experiment(settings.mlflow_experiment)
        mlflow.dspy.autolog()
        get_logger(__name__).info("mlflow_tracing_on", experiment=settings.mlflow_experiment, mode="async")
    except Exception as exc:
        get_logger(__name__).warning("mlflow_autolog_unavailable", error=str(exc))


def get_logger(name: str = "app"):
    return structlog.get_logger(name)
