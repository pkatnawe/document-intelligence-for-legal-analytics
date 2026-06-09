"""DSPy signatures — the LLM-interaction layer.

Each signature is a typed contract: declared inputs and a Pydantic `Invoice` output. The
schema *is* the validation contract, so the document-handling, model-interaction, and
validation concerns stay cleanly separated (a requirement of the brief). Two front-ends
share one output type: text (digital PDFs) and image (scanned / image-only PDFs).
"""
import dspy

from app.validation.schema import Invoice


class ExtractInvoice(dspy.Signature):
    """Extract structured invoice data (header + line items) from raw document text."""

    document_text: str = dspy.InputField(desc="raw text extracted from the PDF")
    invoice: Invoice = dspy.OutputField(desc="the structured invoice")


class ExtractInvoiceVision(dspy.Signature):
    """Extract structured invoice data (header + line items) from a scanned invoice image."""

    page_image: dspy.Image = dspy.InputField(desc="rendered page image of a scanned / image-only invoice")
    invoice: Invoice = dspy.OutputField(desc="the structured invoice")
