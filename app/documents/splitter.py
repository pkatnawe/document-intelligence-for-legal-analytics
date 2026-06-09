"""Ingestion preprocessing — split a multi-invoice PDF into single-invoice documents.

The extraction service assumes one document = one invoice. Real uploads aren't always that
clean: the case dataset is a single PDF holding three unrelated invoices (Uber, WeWork,
Cargo), one per page. This splitter "bursts" such a file into one single-page PDF per page,
dropping near-blank pages, so each invoice becomes an independent job with its own retained
document and audit trail.

This is deliberately a *preprocessing* step, separate from extraction: in the platform it
sits in ingestion alongside format conversion and classification. PyMuPDF does the page
split with no external dependency.
"""
from __future__ import annotations

from dataclasses import dataclass

import fitz  # PyMuPDF


@dataclass
class SplitPage:
    index: int      # 0-based page number in the source PDF
    pdf: bytes      # a standalone single-page PDF


def _ink_ratio(page, dpi: int = 72) -> float:
    """Cheap content proxy: fraction of non-white pixels at low DPI."""
    data = page.get_pixmap(dpi=dpi).samples
    return 0.0 if not data else 1.0 - (data.count(255) / len(data))


def split_pdf(data: bytes, min_ink: float = 0.01) -> list[SplitPage]:
    """Return one single-page PDF per content page. A single-page input round-trips to one
    document, so feeding an already-single invoice through this step is harmless."""
    src = fitz.open(stream=data, filetype="pdf")
    try:
        out: list[SplitPage] = []
        for i in range(src.page_count):
            if _ink_ratio(src[i]) < min_ink:
                continue  # blank cover / separator page — not an invoice
            one = fitz.open()
            one.insert_pdf(src, from_page=i, to_page=i)
            out.append(SplitPage(index=i, pdf=one.tobytes()))
            one.close()
        # Never return nothing: if every page looked blank, keep the densest page.
        if not out and src.page_count:
            i = max(range(src.page_count), key=lambda n: _ink_ratio(src[n]))
            one = fitz.open()
            one.insert_pdf(src, from_page=i, to_page=i)
            out.append(SplitPage(index=i, pdf=one.tobytes()))
            one.close()
        return out
    finally:
        src.close()
