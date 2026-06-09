"""Central configuration. All secrets come from the environment — never hard-coded."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # Databricks workspace + auth, used to reach Foundation Model serving endpoints.
    # On Databricks Apps these are provided to the app's service principal automatically.
    host: str = os.environ.get("DATABRICKS_HOST", "").rstrip("/")
    token: str = os.environ.get("DATABRICKS_TOKEN", "")

    # Speed-first model cascade. These are Databricks serving-endpoint names.
    tier1_model: str = os.environ.get("TIER1_MODEL", "databricks-gemini-3-5-flash")
    tier2_model: str = os.environ.get("TIER2_MODEL", "databricks-claude-opus-4-8")

    # MLflow experiment that receives the DSPy traces (the model-audit layer). Empty
    # disables remote tracing (e.g. pure offline unit tests).
    mlflow_experiment: str = os.environ.get("MLFLOW_EXPERIMENT", "")

    # Retry budget for transient model/API errors (failure case (c)).
    max_attempts: int = int(os.environ.get("MAX_ATTEMPTS", "3"))

    @property
    def serving_base(self) -> str:
        """OpenAI-compatible base URL for Databricks serving endpoints."""
        return f"{self.host}/serving-endpoints" if self.host else ""


settings = Settings()
