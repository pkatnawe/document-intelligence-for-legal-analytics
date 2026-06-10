"""Post-extraction normalization — deterministic consistency fixes that need no re-read.

A model can read the individual rows of an invoice correctly yet mis-fill an *aggregate*
field. The clearest case: an Uber receipt lists `TPS 2.32` and `TVQ 4.64` as line items
(correct), but the model writes `tax = 11.03` (it grabbed the tip). The aggregate is, by
definition, the sum of its itemized tax parts — so we derive it rather than trust the model's
arithmetic. This is the same parts-vs-whole principle as `reconcile`, applied to fix instead
of just flag. It generalizes (GST/HST/PST/QST/TPS/TVQ/VAT) and is a no-op when the model
already agrees or there are no itemized tax lines.
"""
from __future__ import annotations

import re

from app.validation.schema import Invoice

# Tax labels as whole words, incl. the French-Canadian codes (TPS=GST, TVQ=QST).
_TAX_RE = re.compile(r"\b(gst|hst|pst|qst|tps|tvq|vat|sales tax)\b", re.IGNORECASE)


def _is_tax_line(description: str | None) -> bool:
    return bool(description and _TAX_RE.search(description))


def normalize_invoice(inv: Invoice) -> Invoice:
    """Derive `tax` from itemized tax lines when present; otherwise return the invoice as-is."""
    tax_amounts = [li.amount for li in inv.line_items
                   if li.amount is not None and _is_tax_line(li.description)]
    if not tax_amounts:
        return inv
    derived = round(sum(tax_amounts), 2)
    if inv.tax is not None and abs(inv.tax - derived) <= 0.01:
        return inv  # model already agrees — no change
    return inv.model_copy(update={"tax": derived})
