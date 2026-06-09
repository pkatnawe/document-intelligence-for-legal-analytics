"""Wire DSPy to Databricks Foundation Model serving endpoints.

Speed-first cascade: tier-1 is a fast, vision-capable model (the default); tier-2 is a
premium model used only on escalation. DSPy talks to the endpoints through LiteLLM's
`databricks/` provider, which reads DATABRICKS_API_BASE / DATABRICKS_API_KEY. On
Databricks Apps these are supplied to the service principal automatically.
"""
from __future__ import annotations

import os

import dspy

from app.config import settings
from app.llm.signatures import ExtractInvoice, ExtractInvoiceVision

FAST: "dspy.LM | None" = None
PREMIUM: "dspy.LM | None" = None
extract_text = None    # dspy.ChainOfThought(ExtractInvoice)
extract_vision = None   # dspy.ChainOfThought(ExtractInvoiceVision)


def configure() -> None:
    """Initialise the model tiers and predictors. Safe to call once at startup."""
    global FAST, PREMIUM, extract_text, extract_vision

    if settings.serving_base and settings.token:
        os.environ.setdefault("DATABRICKS_API_BASE", settings.serving_base)
        os.environ.setdefault("DATABRICKS_API_KEY", settings.token)

    FAST = dspy.LM(f"databricks/{settings.tier1_model}", cache=False)
    PREMIUM = dspy.LM(f"databricks/{settings.tier2_model}", cache=False)
    dspy.configure(lm=FAST)

    # Chain-of-Thought: the model reasons about the layout/amounts before committing to the
    # typed output — measurably better on messy receipts than a bare Predict. The extra
    # `reasoning` field is internal; callers still read `.invoice`.
    extract_text = dspy.ChainOfThought(ExtractInvoice)
    extract_vision = dspy.ChainOfThought(ExtractInvoiceVision)
