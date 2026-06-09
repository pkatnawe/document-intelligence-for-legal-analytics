"""The data contract.

`Invoice` is the single source of truth, shared by the DSPy extraction signature and the
validation layer. When the model returns something that does not fit this schema, that is
failure case (a) — caught at the framework boundary, not by hand-rolled parsing.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LineItem(BaseModel):
    description: str
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: float


class Invoice(BaseModel):
    """Header + line items extracted from a single PDF invoice.

    Field optionality is set by what real invoices actually carry. The case dataset is
    three very different documents — an Uber ride receipt (no invoice number, taxes as
    line items), a WeWork invoice (explicit subtotal + GST), and a Cargo subscription
    receipt (payment method, zero tax) — so only `total` is structurally required; the
    rest are optional. `vendor`/`bill_to` are the "involved parties" the brief calls out.
    """
    invoice_number: Optional[str] = None   # ride receipts (Uber) have none
    invoice_date: Optional[str] = None
    vendor: Optional[str] = None           # who issued it (involved party)
    bill_to: Optional[str] = None          # the client (involved party)
    currency: Optional[str] = None
    subtotal: Optional[float] = None       # amount before tax, when stated
    tax: Optional[float] = None            # total tax (GST/QST/VAT…), when stated
    total: float = Field(ge=0)             # the one amount every invoice has
    payment_method: Optional[str] = None   # e.g. "American Express …1004"
    line_items: list[LineItem] = Field(default_factory=list)


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class Job(BaseModel):
    """An extraction job. Status survives restarts via the persistent store."""
    id: str
    status: JobStatus = JobStatus.PENDING
    filename: Optional[str] = None
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    was_scan: Optional[bool] = None
    source_path: Optional[str] = None  # UC Volume path of the retained raw PDF
    tier_used: Optional[str] = None
    result: Optional[Invoice] = None   # one document = one invoice
    error: Optional[str] = None
