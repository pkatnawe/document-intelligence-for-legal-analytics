"""Shared fixtures: small PDFs generated in-memory with PyMuPDF (no fixture files)."""
import fitz  # PyMuPDF
import pytest


def _pdf(pages: list[str]) -> bytes:
    """Build a PDF; each list item is a page's text ('' = a blank page). Non-blank pages get
    filler lines so their ink clears the splitter's blank-page threshold, like a real invoice."""
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        if text:
            filler = "\n".join(f"line item {i}: description and amount $ {i}.00" for i in range(24))
            page.insert_text((72, 100), text + "\n" + filler, fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def text_pdf() -> bytes:
    """A single digital invoice with a real text layer."""
    return _pdf(["INVOICE\nInvoice Number: INV-1\nBill To: Acme Corp\nTotal: $100.00"])


@pytest.fixture
def three_page_pdf() -> bytes:
    """Three invoices in one file (the case-dataset shape)."""
    return _pdf(["INVOICE A\nTotal: $10", "INVOICE B\nTotal: $20", "INVOICE C\nTotal: $30"])


@pytest.fixture
def pdf_with_blank() -> bytes:
    """One content page + one blank page (the blank must be dropped)."""
    return _pdf(["INVOICE\nTotal: $5", ""])


@pytest.fixture
def scan_like_pdf() -> bytes:
    """A page with ink but no text layer — exercises the vision (scan) path."""
    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(fitz.Rect(50, 50, 500, 700), fill=(0, 0, 0))  # filled box, no text
    data = doc.tobytes()
    doc.close()
    return data
