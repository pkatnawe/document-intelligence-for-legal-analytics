import pytest
from pydantic import ValidationError

from app.validation.schema import Invoice, LineItem


def test_valid_invoice():
    inv = Invoice(
        invoice_number="INV-2024-0042",
        subtotal=46.11,
        tax=0.0,
        total=46.11,
        line_items=[LineItem(description="Consulting", quantity=1, unit_price=46.11, amount=46.11)],
    )
    assert inv.total == 46.11
    assert inv.line_items[0].amount == 46.11


def test_receipt_without_invoice_number_is_valid():
    # An Uber ride receipt has no invoice number — that must NOT be a validation failure.
    inv = Invoice(vendor="Uber", currency="CAD", total=64.46)
    assert inv.invoice_number is None
    assert inv.vendor == "Uber"


def test_negative_total_allowed_for_credit_notes():
    # A credit note / refund legitimately has a negative total — the schema must accept it.
    inv = Invoice(invoice_number="CN-1", total=-42.50)
    assert inv.total == -42.50


def test_missing_total_allowed():
    # The schema is permissive so a varied test set never hard-fails on a missing field;
    # a missing total surfaces as None (caught downstream), not a validation error.
    inv = Invoice(invoice_number="INV-1")
    assert inv.total is None


def test_non_numeric_total_rejected():
    # Type errors are still caught at the boundary — that's failure case (a).
    with pytest.raises(ValidationError):
        Invoice(invoice_number="INV-1", total="N/A")  # type: ignore[arg-type]


def test_json_roundtrip():
    inv = Invoice(invoice_number="INV-2", total=10)
    assert Invoice.model_validate_json(inv.model_dump_json()) == inv
