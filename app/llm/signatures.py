"""DSPy signatures — the LLM-interaction layer.

Each signature is a typed contract: declared inputs and a Pydantic `Invoice` output. The
schema *is* the validation contract, so the document-handling, model-interaction, and
validation concerns stay cleanly separated (a requirement of the brief). Two front-ends
share one output type: text (digital PDFs) and image (scanned / image-only PDFs).
"""
import dspy

from app.validation.schema import Invoice

# One robust rule set, shared by the text and vision front-ends so they behave identically.
# These rules are written to survive a varied test set — different vendors, layouts,
# currencies, languages, receipts vs. formal invoices, and credit notes.
_RULES = """Read the whole document and reason about its layout before answering.

AMOUNTS
- Transcribe every monetary value EXACTLY as printed, keeping its decimal point (3.17 is
  3.17, never 31.7). Use a '.' decimal separator; drop thousands separators and currency
  symbols from numeric fields.
- `currency`: output the ISO code — CAD, USD, EUR, GBP. Convert symbols (CA$ -> CAD, a bare
  $ in a US address context -> USD).
- `total` is the FINAL amount due or paid — the value labeled Total / Total Paid / Amount
  Due / Balance Due / Grand Total. `subtotal` is the amount labeled Subtotal (before
  tax/fees). NEVER swap them. If several totals appear (per page, running), use the final
  grand total. On a credit note / refund, `total` may be NEGATIVE.
- `tax` is the SUM of EVERY tax line. Tax lines are labeled tax / sales tax / VAT, or the
  Canadian codes GST / HST / PST / QST and their French equivalents TPS (= GST) and TVQ
  (= QST). Add them ALL together — e.g. a receipt with both TPS and TVQ has tax = TPS + TVQ.
  A Tip, gratuity, booking fee, reservation fee, surcharge, or service fee is **NOT** tax.
  Also list each tax line in `line_items`.

LINE ITEMS
- Put EVERY charge row in `line_items`, each read exactly: fares, fees, taxes, tips,
  surcharges, subscription lines, shipping, and discounts. A discount or credit is a
  NEGATIVE amount.

IDENTITY & DATES
- `vendor` is the seller/supplier that ISSUED the invoice; `bill_to` is the customer being
  charged. Do not confuse them.
- Transcribe dates as printed.

HONESTY
- Only fill a field the document actually shows. If a field is absent, return null — NEVER
  substitute a card number, phone number, date, or address for an invoice number, and never
  invent a value. When unsure, prefer null over a guess.
"""


class ExtractInvoice(dspy.Signature):
    __doc__ = "Extract structured invoice data (header + line items) from raw document text.\n\n" + _RULES

    document_text: str = dspy.InputField(desc="raw text extracted from the PDF")
    invoice: Invoice = dspy.OutputField(desc="the structured invoice")


class ExtractInvoiceVision(dspy.Signature):
    __doc__ = "Extract structured invoice data (header + line items) from a scanned invoice image.\n\n" + _RULES

    page_image: dspy.Image = dspy.InputField(desc="rendered page image of a scanned / image-only invoice")
    invoice: Invoice = dspy.OutputField(desc="the structured invoice")
