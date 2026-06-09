"""Structured logging + MLflow tracing (the model-audit layer).

`mlflow.dspy.autolog()` records every model call — input, rendered prompt, model, output,
tokens, latency — so each extraction is reproducible. That is the model-audit layer; the
business-audit layer (document state changes) lives in the job store's audit_events.
"""
from __future__ import annotations

import logging

import structlog

from app.config import settings


def configure(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", level=level)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )
    try:
        import mlflow

        # Point traces at the workspace experiment so every model call is logged where an
        # auditor can query it. On Databricks Apps the tracking URI is the workspace; set
        # it explicitly so the same code traces from a laptop too.
        if settings.mlflow_experiment:
            mlflow.set_tracking_uri("databricks")
            mlflow.set_experiment(settings.mlflow_experiment)
        mlflow.dspy.autolog()
        get_logger(__name__).info("mlflow_tracing_on", experiment=settings.mlflow_experiment or "(local)")
    except Exception as exc:  # optional locally; required for the audit layer when deployed
        get_logger(__name__).warning("mlflow_autolog_unavailable", error=str(exc))


def get_logger(name: str = "app"):
    return structlog.get_logger(name)
