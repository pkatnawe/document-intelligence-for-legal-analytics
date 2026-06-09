"""DSPy signatures — the LLM-interaction layer.

Each signature is a typed contract: declared inputs and a Pydantic `Invoice` output. The
schema *is* the validation contract, so the document-handling, model-interaction, and
validation concerns stay cleanly separated (a requirement of the brief). Two front-ends
share one output type: text (digital PDFs) and image (scanned / image-only PDFs).
"""
import dspy

from app.validation.schema import Invoice


class ExtractInvoice(dspy.Signature):
    """Extract structured invoice data (header + line items) from raw document text.

    Transcribe values exactly as printed — keep the decimal point (3.17 is 3.17, never 31.7).
    `total` is the amount labeled Total / Total Paid / Amount Due; `subtotal` is the amount
    labeled Subtotal — never swap them. `tax` is only a value labeled tax / GST / HST / QST /
    VAT — a tip is NOT tax. Put every charge row (fares, fees, taxes, tips, subscription
    lines) in `line_items`. Only fill a field the document actually shows: if there is no
    invoice number (e.g. a ride receipt), return null — never substitute a card number,
    phone number, or date.
    """

    document_text: str = dspy.InputField(desc="raw text extracted from the PDF")
    invoice: Invoice = dspy.OutputField(desc="the structured invoice")


class ExtractInvoiceVision(dspy.Signature):
    """Extract structured invoice data (header + line items) from a scanned invoice image.

    Transcribe values exactly as printed — keep the decimal point (3.17 is 3.17, never 31.7).
    `total` is the amount labeled Total / Total Paid / Amount Due; `subtotal` is the amount
    labeled Subtotal — never swap them. `tax` is only a value labeled tax / GST / HST / QST /
    VAT — a tip is NOT tax. Put every charge row (fares, fees, taxes, tips, subscription
    lines) in `line_items`. Only fill a field the document actually shows: if there is no
    invoice number (e.g. a ride receipt), return null — never substitute a card number,
    phone number, or date.
    """

    page_image: dspy.Image = dspy.InputField(desc="rendered page image of a scanned / image-only invoice")
    invoice: Invoice = dspy.OutputField(desc="the structured invoice")
