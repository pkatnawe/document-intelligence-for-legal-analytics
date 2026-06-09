"""Correctness checks beyond schema conformance.

Schema validation proves the output is *well-typed* (a non-negative float total, a string
vendor…), but a weak model can still return values that are well-typed and *wrong* — e.g. a
total that doesn't match the line items. That would pass schema validation and SUCCEED
silently, which for a legal client is the worst failure mode.

`reconcile` is a cheap arithmetic sanity check: when the invoice has line items, they should
sum to the total. If they don't, the extraction is internally inconsistent and is flagged —
the caller escalates to a stronger model and, failing that, routes it to human review rather
than storing a confident wrong answer.

We deliberately check only line-items-vs-total, because it holds for every invoice shape in
the dataset when extracted correctly (the Uber receipt folds its taxes/fees into line items,
so a subtotal+tax==total check would false-positive on a *correct* Uber extraction).
"""
from __future__ import annotations

from app.validation.schema import Invoice


def reconcile(inv: Invoice, abs_tol: float = 0.02, rel_tol: float = 0.01) -> list[str]:
    """Return a list of human-readable consistency warnings (empty == looks consistent)."""
    warnings: list[str] = []
    if inv.line_items:
        line_sum = round(sum(li.amount for li in inv.line_items), 2)
        tolerance = max(abs_tol, rel_tol * inv.total)
        if abs(line_sum - inv.total) > tolerance:
            warnings.append(
                f"line items sum to {line_sum:.2f} but the total is {inv.total:.2f} "
                f"— the extracted amounts may be wrong"
            )
    return warnings
