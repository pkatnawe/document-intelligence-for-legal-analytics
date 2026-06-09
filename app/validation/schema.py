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
    description: str = Field(description="the charge's label, exactly as printed (e.g. 'Base Fare', 'Tip')")
    quantity: Optional[float] = Field(default=None, description="quantity if shown, else null")
    unit_price: Optional[float] = Field(default=None, description="price per unit if shown, else null")
    amount: float = Field(description="the line's amount, read exactly with its decimal point (e.g. 3.17, not 31.7)")


class Invoice(BaseModel):
    """Header + line items extracted from a single PDF invoice.

    Field optionality is set by what real invoices actually carry. The case dataset is
    three very different documents — an Uber ride receipt (no invoice number, taxes as
    line items), a WeWork invoice (explicit subtotal + GST), and a Cargo subscription
    receipt (payment method, zero tax) — so only `total` is structurally required; the
    rest are optional. `vendor`/`bill_to` are the "involved parties" the brief calls out.
    """
    invoice_number: Optional[str] = Field(
        default=None,
        description="the invoice/receipt number if one is explicitly shown; null if there is "
        "none (e.g. a ride receipt). NEVER use a card number, phone number, or date.",
    )
    invoice_date: Optional[str] = Field(default=None, description="the invoice/issue date if shown")
    vendor: Optional[str] = Field(default=None, description="the company that issued the invoice (the seller/supplier name only)")
    bill_to: Optional[str] = Field(default=None, description="who the invoice is billed to (the customer/client)")
    currency: Optional[str] = Field(default=None, description="ISO currency or symbol, e.g. CAD, USD")
    subtotal: Optional[float] = Field(default=None, description="the amount labeled 'Subtotal' (before tax/fees); null if not shown")
    tax: Optional[float] = Field(default=None, description="ONLY a value explicitly labeled tax/GST/HST/QST/VAT; null if none. A tip is NOT tax.")
    total: float = Field(ge=0, description="the final amount due — the value labeled 'Total' / 'Total Paid' / 'Amount Due'")
    payment_method: Optional[str] = Field(default=None, description="how it was paid, e.g. 'American Express …1004'")
    line_items: list[LineItem] = Field(
        default_factory=list,
        description="every individual charge row (fares, fees, taxes, tips, subscription lines), each read exactly",
    )


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
    warnings: list[str] = Field(default_factory=list)  # consistency flags → needs human review
    error: Optional[str] = None
